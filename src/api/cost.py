"""GET /cost-summary — per-session + all-time running token/cost totals.

Aggregates CostRecord rows (written per LLM call since Phase 1). The
all_time block sums every CostRecord in the DB; the session block (only
present when a session_id is passed) scopes to that session's rows via
CostRecord.query_result_id -> QueryResult.session_id. Each row's
estimated_cost_usd was computed at write time from the Gemini price table
in config/settings.py; this read path sums those authoritative values (per
spec/api.md success criterion: all_time == sum of CostRecord.estimated_cost_usd).

Carries only token counts, cost figures, and call counts — never raw rows.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Query as SAQuery, Session

from api._common import ok
from db.session import get_session
from db.models import CostRecord, QueryResult
from domain.cost import CostSummaryResponse, CostTotals
from observability.events import get_logger

router = APIRouter()
log = get_logger("cost")


def _aggregate(query: SAQuery) -> CostTotals:
    """Sum tokens/cost/count over a (possibly filtered) CostRecord query.

    coalesce guarantees zeroed totals over an empty/over-filtered result
    rather than NULLs (per spec/api.md — no error cases, empty -> zeros).
    """
    row = query.with_entities(
        func.coalesce(func.sum(CostRecord.prompt_tokens), 0),
        func.coalesce(func.sum(CostRecord.completion_tokens), 0),
        func.coalesce(func.sum(CostRecord.estimated_cost_usd), 0),
        func.count(CostRecord.id),
    ).one()
    return CostTotals(
        prompt_tokens=int(row[0]),
        completion_tokens=int(row[1]),
        estimated_cost_usd=float(row[2]),
        call_count=int(row[3]),
    )


@router.get("/cost-summary")
def cost_summary(
    session_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict:
    all_time = _aggregate(session.query(CostRecord))

    session_totals: CostTotals | None = None
    if session_id is not None:
        scoped = (
            session.query(CostRecord)
            .join(QueryResult, CostRecord.query_result_id == QueryResult.id)
            .filter(QueryResult.session_id == session_id)
        )
        session_totals = _aggregate(scoped)

    log.info(
        "cost_summary_read",
        session_id=session_id,
        all_time_calls=all_time.call_count,
        all_time_cost_usd=all_time.estimated_cost_usd,
        session_calls=(session_totals.call_count if session_totals else None),
    )

    return ok(
        CostSummaryResponse(
            session=session_totals,
            all_time=all_time,
        ).model_dump()
    )
