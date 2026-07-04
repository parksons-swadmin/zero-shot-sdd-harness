"""HTTP layer over the deterministic AR-aging engine.

Two stateless routes, both ``multipart/form-data``:

- ``POST /api/preview``  — parse headers, propose the six-field mapping, return a
  10-row preview + parse-time data-quality flags. The server keeps nothing.
- ``POST /api/compute``  — apply the confirmed mapping, run the deterministic
  pipeline over the full sheet, return the ``DashboardResult``.

No DB, no LLM, no network. Structural failures raise ``PipelineError`` in the
engine and are rendered here via ``api_error`` (never a raw traceback). Logs
record aggregate counts/timings only — never file contents or customer data.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from api._common import api_error, ok
from config.settings import get_settings
from domain.mapping import ColumnMapping
from graph.runner import PipelineError, build_preview, run_analysis
from observability.events import get_logger

router = APIRouter(prefix="/api")

_log = get_logger("api.analysis")


def _enforce_upload_size(file_bytes: bytes) -> None:
    """Reject over-large uploads before touching the parser."""
    mb = get_settings().max_upload_mb
    if len(file_bytes) > mb * 1024 * 1024:
        raise api_error("TOO_LARGE", f"File exceeds {mb} MB.", 413)


@router.post("/preview")
async def preview(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None),
) -> dict:
    """Parse headers, auto-detect the mapping, return preview rows + parse flags."""
    file_bytes = await file.read()
    _enforce_upload_size(file_bytes)

    try:
        result = build_preview(file_bytes=file_bytes, sheet_name=sheet_name)
    except PipelineError as exc:
        raise api_error(exc.code, exc.message, exc.status)

    _log.info(
        "api.preview",
        filename=file.filename,
        size_bytes=len(file_bytes),
        columns=len(result.columns),
        flags=len(result.parse_flags),
    )
    return ok(result.model_dump(mode="json"))


@router.post("/compute")
async def compute(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None),
    mapping: str = Form(...),
) -> dict:
    """Apply the confirmed mapping and return the exact ``DashboardResult``."""
    file_bytes = await file.read()
    _enforce_upload_size(file_bytes)

    try:
        payload = json.loads(mapping)
        column_mapping = ColumnMapping(**payload)
    except (json.JSONDecodeError, ValidationError, TypeError):
        raise api_error("BAD_MAPPING", "Invalid or incomplete mapping payload.", 400)

    try:
        metrics = run_analysis(
            file_bytes=file_bytes, sheet_name=sheet_name, mapping=column_mapping
        )
    except PipelineError as exc:
        raise api_error(exc.code, exc.message, exc.status)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - never leak a traceback to the client
        raise api_error("INTERNAL", "Unexpected error while computing metrics.", 500)

    result = {
        **metrics.model_dump(mode="json"),
        "source_filename": file.filename,
        "sheet_name": sheet_name,
    }
    _log.info(
        "api.compute",
        filename=file.filename,
        size_bytes=len(file_bytes),
        row_count=metrics.row_count,
    )
    return ok(result)
