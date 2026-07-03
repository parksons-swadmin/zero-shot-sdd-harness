from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api._common import ok
from db.session import get_session
from db.models import AuditLogEntry
from domain.audit import AuditLogEntryOut, AuditLogListResponse
from observability.events import get_logger

router = APIRouter()
log = get_logger("audit")

_MAX_LIMIT = 200


@router.get("/audit-log")
def list_audit_log(
    session_id: str | None = Query(default=None),
    dataset_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> dict:
    limit = min(limit, _MAX_LIMIT)

    query = session.query(AuditLogEntry)
    if session_id is not None:
        query = query.filter(AuditLogEntry.session_id == session_id)
    if dataset_id is not None:
        query = query.filter(AuditLogEntry.dataset_id == dataset_id)
    if event_type is not None:
        query = query.filter(AuditLogEntry.event_type == event_type)

    total = query.count()

    rows = (
        query.order_by(AuditLogEntry.created_at.asc(), AuditLogEntry.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    entries = [
        AuditLogEntryOut(
            id=row.id,
            session_id=row.session_id,
            dataset_id=row.dataset_id,
            query_result_id=row.query_result_id,
            event_type=row.event_type,
            detail=row.detail_json or {},
            created_at=row.created_at,
        )
        for row in rows
    ]

    log.info(
        "audit_log_listed",
        session_id=session_id,
        dataset_id=dataset_id,
        event_type=event_type,
        total=total,
        returned=len(entries),
        limit=limit,
        offset=offset,
    )

    return ok(
        AuditLogListResponse(
            entries=entries,
            total=total,
            limit=limit,
            offset=offset,
        ).model_dump()
    )
