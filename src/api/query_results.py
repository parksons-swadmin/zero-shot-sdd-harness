from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api._common import api_error
from db.session import get_session
from db.models import Dataset, QueryResult
from observability.events import get_logger

router = APIRouter()
log = get_logger("query_results")


@router.get("/query-results/{query_result_id}/export")
def export_query_result(
    query_result_id: str,
    session: Session = Depends(get_session),
) -> FileResponse:
    query_result = session.get(QueryResult, query_result_id)
    if query_result is None:
        raise api_error("NOT_FOUND", f"Query result {query_result_id} not found", 404)

    if not query_result.export_dataset_id:
        raise api_error(
            "NOT_FOUND",
            f"Query result {query_result_id} produced no export",
            404,
        )

    dataset = session.get(Dataset, query_result.export_dataset_id)
    if dataset is None:
        raise api_error(
            "NOT_FOUND",
            f"Derived dataset {query_result.export_dataset_id} not found",
            404,
        )

    export_path = Path(dataset.original_path)
    if not export_path.is_file():
        log.error(
            "export_file_missing",
            query_result_id=query_result_id,
            export_dataset_id=dataset.id,
            path=str(export_path),
        )
        raise api_error("NOT_FOUND", "Export file is missing on disk", 404)

    download_name = f"{Path(dataset.filename).stem}_derived.csv"
    log.info(
        "export_downloaded",
        query_result_id=query_result_id,
        export_dataset_id=dataset.id,
        download_name=download_name,
    )
    return FileResponse(
        path=str(export_path),
        media_type="text/csv",
        filename=download_name,
    )
