import io
import time
from pathlib import Path
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session

from api._common import ok, api_error
from config.settings import get_settings
from db.session import get_session
from db.models import Dataset, DatasetProfile, CleaningReport, AuditLogEntry
from domain.dataset import (
    DatasetUploadResponse,
    DatasetProfileOut,
    CleaningReportOut,
)
from observability.events import get_logger
from storage.files import (
    original_path_for,
    save_upload_stream,
    save_cleaned_parquet,
    remove_dataset_files,
)
from tools.cleaning import clean_dataset
from tools.profiling import build_profile

router = APIRouter()
log = get_logger("datasets")

_SPREADSHEET_EXTS = {".xlsx", ".xls"}
_DELIMITED_EXTS = {".csv", ".tsv", ".txt"}


def _load_dataframe(path: Path, ext: str) -> pd.DataFrame:
    if ext in _SPREADSHEET_EXTS:
        return pd.read_excel(path)
    if ext == ".tsv":
        return pd.read_csv(path, sep="\t")
    return pd.read_csv(path)


def _write_audit(session: Session, dataset_id: str, event_type: str, detail: dict) -> None:
    session.add(
        AuditLogEntry(
            dataset_id=dataset_id,
            event_type=event_type,
            detail_json=detail,
        )
    )
    session.flush()


def _build_response(dataset: Dataset, profile: DatasetProfile, report: CleaningReport) -> dict:
    resp = DatasetUploadResponse(
        dataset_id=dataset.id,
        filename=dataset.filename,
        row_count=dataset.row_count,
        column_count=dataset.column_count,
        status=dataset.status,
        profile=DatasetProfileOut(columns=profile.columns_json),
        cleaning_report=CleaningReportOut(issues=report.issues_json),
    )
    return resp.model_dump()


@router.post("/datasets")
def create_dataset(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    settings = get_settings()
    max_bytes = settings.max_upload_bytes

    # Reject before the write completes when the client declared a size.
    declared_size = file.size if hasattr(file, "size") else None
    if declared_size is not None and declared_size > max_bytes:
        raise api_error("FILE_TOO_LARGE", "File exceeds AGENT_MAX_UPLOAD_BYTES", 413)

    filename = file.filename or "upload.csv"
    ext = Path(filename).suffix.lower() or ".csv"
    if ext not in _DELIMITED_EXTS | _SPREADSHEET_EXTS:
        ext = ".csv"

    dataset_id = str(uuid4())
    t0 = time.monotonic()
    try:
        original_path, size_bytes = save_upload_stream(dataset_id, ext, file, max_bytes)
    except ValueError:
        remove_dataset_files(dataset_id)
        log.info("dataset_upload_rejected", reason="too_large", dataset_id=dataset_id)
        raise api_error("FILE_TOO_LARGE", "File exceeds AGENT_MAX_UPLOAD_BYTES", 413)
    except OSError as exc:
        remove_dataset_files(dataset_id)
        log.error("dataset_upload_disk_error", dataset_id=dataset_id, error=str(exc))
        raise api_error("STORAGE_ERROR", "Failed to write uploaded file to disk", 500)

    try:
        df = _load_dataframe(original_path, ext)
        if df.shape[1] == 0:
            raise ValueError("no columns parsed")
    except Exception as exc:
        remove_dataset_files(dataset_id)
        log.info("dataset_upload_unparseable", dataset_id=dataset_id, error=str(exc))
        raise api_error("UNPARSEABLE_FILE", "File is not a parseable CSV/TSV/XLSX", 400)

    dataset = Dataset(
        id=dataset_id,
        filename=filename,
        original_path=str(original_path),
        size_bytes=size_bytes,
        status="uploading",
    )
    session.add(dataset)
    session.flush()
    _write_audit(
        session,
        dataset_id,
        "upload",
        {"filename": filename, "size_bytes": size_bytes, "row_count": int(df.shape[0]), "column_count": int(df.shape[1])},
    )
    log.info(
        "dataset_uploaded",
        dataset_id=dataset_id,
        size_bytes=size_bytes,
        row_count=int(df.shape[0]),
        column_count=int(df.shape[1]),
        elapsed_ms=int((time.monotonic() - t0) * 1000),
    )

    try:
        dataset.status = "cleaning"
        t1 = time.monotonic()
        cleaned_df, issues = clean_dataset(df)
        report = CleaningReport(dataset_id=dataset_id, issues_json=issues)
        session.add(report)
        _write_audit(
            session,
            dataset_id,
            "clean",
            {"issue_count": len(issues), "needs_review_count": sum(1 for i in issues if i["needs_review"])},
        )
        log.info(
            "dataset_cleaned",
            dataset_id=dataset_id,
            issue_count=len(issues),
            elapsed_ms=int((time.monotonic() - t1) * 1000),
        )

        cleaned_path = save_cleaned_parquet(dataset_id, cleaned_df)
        dataset.cleaned_path = str(cleaned_path)

        t2 = time.monotonic()
        columns = build_profile(cleaned_df)
        profile = DatasetProfile(dataset_id=dataset_id, columns_json=columns)
        session.add(profile)
        dataset.row_count = int(cleaned_df.shape[0])
        dataset.column_count = int(cleaned_df.shape[1])
        dataset.status = "ready"
        _write_audit(
            session,
            dataset_id,
            "profile",
            {"row_count": dataset.row_count, "column_count": dataset.column_count},
        )
        log.info(
            "dataset_profiled",
            dataset_id=dataset_id,
            row_count=dataset.row_count,
            column_count=dataset.column_count,
            elapsed_ms=int((time.monotonic() - t2) * 1000),
        )
    except Exception as exc:
        dataset.status = "error"
        _write_audit(session, dataset_id, "error", {"stage": "clean_or_profile", "message": str(exc)})
        session.commit()
        log.error("dataset_processing_failed", dataset_id=dataset_id, error=str(exc))
        raise api_error(
            "PROCESSING_FAILED",
            "Cleaning/profiling failed for this file; it could not be recovered.",
            500,
        )

    session.flush()
    return ok(_build_response(dataset, profile, report))


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, session: Session = Depends(get_session)) -> dict:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise api_error("NOT_FOUND", f"Dataset {dataset_id} not found", 404)
    profile = session.query(DatasetProfile).filter(DatasetProfile.dataset_id == dataset_id).first()
    report = session.query(CleaningReport).filter(CleaningReport.dataset_id == dataset_id).first()
    if profile is None or report is None:
        raise api_error("NOT_FOUND", f"Dataset {dataset_id} has no profile/cleaning report yet", 404)
    return ok(_build_response(dataset, profile, report))
