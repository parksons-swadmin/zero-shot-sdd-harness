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
import queue
import threading
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError

from api._common import api_error, ok
from config.settings import get_settings
from domain.mapping import ColumnMapping
from graph.runner import (
    PipelineError,
    build_preview,
    run_analysis,
    run_analysis_streaming,
)
from observability.events import get_logger
from tools.excel_export import build_workbook

router = APIRouter(prefix="/api")

_log = get_logger("api.analysis")

_XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _enforce_upload_size(file_bytes: bytes) -> None:
    """Reject over-large uploads before touching the parser."""
    mb = get_settings().max_upload_mb
    if len(file_bytes) > mb * 1024 * 1024:
        raise api_error("TOO_LARGE", f"File exceeds {mb} MB.", 413)


def _parse_mapping(mapping: str) -> ColumnMapping:
    """Parse + validate the JSON mapping form field (same BAD_MAPPING contract
    used by ``/api/compute``)."""
    try:
        return ColumnMapping(**json.loads(mapping))
    except (json.JSONDecodeError, ValidationError, TypeError):
        raise api_error("BAD_MAPPING", "Invalid or incomplete mapping payload.", 400)


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
    column_mapping = _parse_mapping(mapping)

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


# NOTE: the roadmap labels this "GET /api/export/xlsx", but the server is
# STATELESS and persists NOTHING — it holds no computed result to look up. A GET
# cannot carry the (potentially large) source file + confirmed mapping needed to
# rebuild the workbook, so the client re-POSTs them exactly as it does for
# /api/compute. POST multipart is the only stateless-correct design here.
@router.post("/export/xlsx")
async def export_xlsx(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None),
    mapping: str = Form(...),
) -> Response:
    """Rebuild the dashboard metrics from the re-posted file+mapping and return a
    multi-sheet ``.xlsx`` workbook (attachment). Never returns a partial file."""
    file_bytes = await file.read()
    _enforce_upload_size(file_bytes)
    column_mapping = _parse_mapping(mapping)

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

    try:
        content = build_workbook(
            metrics, source_filename=file.filename or "ar_export.xlsx"
        )
    except Exception:  # noqa: BLE001 - never return a partial/corrupt file
        raise api_error("EXPORT_FAILED", "Could not build the Excel workbook.", 500)

    stem = Path(file.filename).stem if file.filename else "ar_export"
    download_name = f"{stem}_AR_aging_{metrics.as_of.isoformat()}.xlsx"
    _log.info(
        "api.export_xlsx",
        filename=file.filename,
        size_bytes=len(file_bytes),
        row_count=metrics.row_count,
        export_bytes=len(content),
    )
    return Response(
        content=content,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


def _sse(payload: dict) -> str:
    """Serialize one Server-Sent-Events ``data:`` frame."""
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/compute/stream")
async def compute_stream(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None),
    mapping: str = Form(...),
) -> StreamingResponse:
    """Stream coarse ``{phase, rows_done, rows_total}`` progress frames then a
    final ``result`` (or ``error``) frame. The final result is byte-identical to
    ``/api/compute``; the client falls back to ``/api/compute`` if unused."""
    file_bytes = await file.read()
    _enforce_upload_size(file_bytes)
    column_mapping = _parse_mapping(mapping)

    # Run the synchronous CPU-bound pipeline on a worker thread and drain its
    # progress frames off a queue, so the bar advances live (not after compute).
    frames: queue.Queue = queue.Queue()
    outcome: dict = {}

    def on_progress(phase: str, rows_done: int, rows_total: int) -> None:
        frames.put({"phase": phase, "rows_done": rows_done, "rows_total": rows_total})

    def work() -> None:
        try:
            metrics = run_analysis_streaming(
                file_bytes=file_bytes,
                sheet_name=sheet_name,
                mapping=column_mapping,
                progress=on_progress,
            )
            outcome["metrics"] = metrics
        except PipelineError as exc:
            outcome["error"] = {"code": exc.code, "message": exc.message}
        except Exception:  # noqa: BLE001 - never leak a traceback into the stream
            outcome["error"] = {
                "code": "INTERNAL",
                "message": "Unexpected error while computing metrics.",
            }
        finally:
            frames.put(None)  # sentinel: worker finished

    worker = threading.Thread(target=work, daemon=True)
    worker.start()

    def event_stream():
        while True:
            item = frames.get()
            if item is None:
                break
            yield _sse(item)
        worker.join()

        if "error" in outcome:
            yield _sse({"event": "error", **outcome["error"]})
            _log.info("api.compute_stream", filename=file.filename, ok=False)
            return

        metrics = outcome["metrics"]
        result = {
            **metrics.model_dump(mode="json"),
            "source_filename": file.filename,
            "sheet_name": sheet_name,
        }
        yield _sse({"event": "result", "result": result})
        _log.info(
            "api.compute_stream",
            filename=file.filename,
            ok=True,
            row_count=metrics.row_count,
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")
