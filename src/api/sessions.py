from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api._common import ok, api_error
from db.session import create_db_session, get_session
from db.models import CostRecord, Dataset, Message, QueryResult, SessionDataset, SessionRow
from domain.query_result import (
    AskRequest,
    AskResponse,
    KeyNumberOut,
    QueryCostOut,
    QueryResultOut,
)
from domain.session import (
    CreateSessionRequest,
    CreateSessionResponse,
    MessageOut,
    SessionHistoryResponse,
)
from graph.runner import (
    SessionBusyError,
    format_sse_event,
    run_agent,
    run_agent_streaming,
)

router = APIRouter()


@router.post("/sessions")
def create_session(req: CreateSessionRequest, session: Session = Depends(get_session)) -> dict:
    if not req.dataset_ids:
        raise api_error("VALIDATION_ERROR", "dataset_ids must not be empty", 422)

    for dataset_id in req.dataset_ids:
        if session.get(Dataset, dataset_id) is None:
            raise api_error("NOT_FOUND", f"Dataset {dataset_id} not found", 404)

    row = SessionRow()
    session.add(row)
    session.flush()
    for dataset_id in req.dataset_ids:
        session.add(SessionDataset(session_id=row.id, dataset_id=dataset_id))

    return ok(CreateSessionResponse(session_id=row.id, dataset_ids=req.dataset_ids).model_dump())


def _query_cost(session: Session, query_result_id: str) -> QueryCostOut | None:
    """Sum the CostRecord rows for one query_result_id into a per-query cost
    total (Phase 3c). Returns None when no cost rows exist. Carries only token
    counts + USD — never raw rows."""
    rows = (
        session.query(CostRecord)
        .filter(CostRecord.query_result_id == query_result_id)
        .all()
    )
    if not rows:
        return None
    prompt_tokens = sum(int(r.prompt_tokens or 0) for r in rows)
    completion_tokens = sum(int(r.completion_tokens or 0) for r in rows)
    estimated_cost_usd = sum(float(r.estimated_cost_usd or 0) for r in rows)
    return QueryCostOut(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=round(estimated_cost_usd, 6),
    )


def _query_result_out(query_result: QueryResult, session: Session) -> QueryResultOut:
    key_numbers = [KeyNumberOut(**kn) for kn in (query_result.key_numbers_json or [])]
    return QueryResultOut(
        id=query_result.id,
        reasoning_mode=query_result.reasoning_mode,
        summary_text=query_result.summary_text,
        key_numbers=key_numbers,
        table=query_result.table_json,
        chart_spec=query_result.chart_spec_json,
        export_dataset_id=query_result.export_dataset_id,
        generated_code=query_result.generated_code,
        follow_up_questions=query_result.follow_up_questions_json,
        anomaly_flags=query_result.anomaly_flags_json,
        cost=_query_cost(session, query_result.id),
        step_count=query_result.step_count,
        status=query_result.status,
    )


@router.get("/sessions/{session_id}")
def get_session_history(session_id: str, session: Session = Depends(get_session)) -> dict:
    row = session.get(SessionRow, session_id)
    if row is None:
        raise api_error("NOT_FOUND", f"Session {session_id} not found", 404)

    dataset_ids = [
        sd.dataset_id
        for sd in session.query(SessionDataset)
        .filter(SessionDataset.session_id == session_id)
        .all()
    ]

    messages = (
        session.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    results_by_message: dict[str, QueryResult] = {
        qr.message_id: qr
        for qr in session.query(QueryResult)
        .filter(QueryResult.session_id == session_id)
        .all()
    }

    message_outs = [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            created_at=m.created_at,
            query_result=(
                _query_result_out(results_by_message[m.id], session)
                if m.id in results_by_message
                else None
            ),
        )
        for m in messages
    ]

    return ok(
        SessionHistoryResponse(
            session_id=session_id,
            dataset_ids=dataset_ids,
            messages=message_outs,
        ).model_dump()
    )


@router.post("/sessions/{session_id}/messages")
def create_message(session_id: str, req: AskRequest, session: Session = Depends(get_session)) -> dict:
    row = session.get(SessionRow, session_id)
    if row is None:
        raise api_error("NOT_FOUND", f"Session {session_id} not found", 404)

    if not req.question or not req.question.strip():
        raise api_error("VALIDATION_ERROR", "question must not be empty", 422)

    dataset_ids = [
        sd.dataset_id
        for sd in session.query(SessionDataset).filter(SessionDataset.session_id == session_id).all()
    ]

    try:
        final_state = run_agent(session_id, dataset_ids, req.question)
    except SessionBusyError as exc:
        raise api_error("CONFLICT", str(exc), 409)

    query_result_id = final_state.get("query_result_id")
    message_id = final_state.get("message_id")

    if final_state.get("status") == "failed" or not query_result_id:
        # The graph failed before finalize (e.g. Gemini error, sandbox guard
        # rejection, timeout). Per spec/api.md this is still a 200 with the
        # failure surfaced as a human-readable query_result, never a raw
        # stack trace and never an unhandled 500.
        error_detail = final_state.get("error") or "The question could not be answered."
        return ok(AskResponse(
            message_id=message_id or "",
            query_result=QueryResultOut(
                id="",
                reasoning_mode=final_state.get("reasoning_mode") or "simple",
                summary_text=f"Sorry, I couldn't answer that question: {error_detail}",
                key_numbers=[],
                generated_code=final_state.get("generated_code") or "",
                step_count=int(final_state.get("step_count") or 0),
                status="failed",
            ),
        ).model_dump())

    query_result = session.get(QueryResult, query_result_id)
    if query_result is None:
        raise api_error("NOT_FOUND", "Query result not found after run", 500)

    return ok(AskResponse(
        message_id=message_id,
        query_result=_query_result_out(query_result, session),
    ).model_dump())


@router.post("/sessions/{session_id}/messages/stream")
def create_message_stream(
    session_id: str, req: AskRequest, session: Session = Depends(get_session)
) -> StreamingResponse:
    """SSE variant of the ask endpoint (Phase 3c). Returns a text/event-stream
    of `step` -> `answer_chunk` -> `result` (or `error`) -> `done` frames. The
    non-streaming POST above is unchanged and remains the fallback.

    404 (unknown session) and 422 (empty question) are returned as normal JSON
    errors BEFORE streaming begins; a run failure after streaming begins is an
    in-stream `error` event with a 200/text-event-stream response.
    """
    row = session.get(SessionRow, session_id)
    if row is None:
        raise api_error("NOT_FOUND", f"Session {session_id} not found", 404)

    if not req.question or not req.question.strip():
        raise api_error("VALIDATION_ERROR", "question must not be empty", 422)

    dataset_ids = [
        sd.dataset_id
        for sd in session.query(SessionDataset).filter(SessionDataset.session_id == session_id).all()
    ]
    question = req.question

    def event_stream():
        stream = run_agent_streaming(session_id, dataset_ids, question)
        try:
            for event in stream:
                etype = event["event"]
                if etype == "result":
                    # finalize has committed; load the authoritative QueryResult
                    # (with per-query cost) in a fresh session — the request-scoped
                    # Depends session may be closed once the body starts streaming.
                    with create_db_session() as fresh:
                        query_result = fresh.get(QueryResult, event["query_result_id"])
                        if query_result is None:
                            yield format_sse_event("error", {
                                "message": "Query result not found after run.",
                                "status": "failed",
                            })
                            continue
                        out = _query_result_out(query_result, fresh)
                    yield format_sse_event("result", {
                        "message_id": event.get("message_id") or "",
                        "query_result": out.model_dump(),
                    })
                else:
                    yield format_sse_event(etype, event.get("data", {}))
        except SessionBusyError as exc:
            yield format_sse_event("error", {"message": str(exc), "status": "failed"})
            yield format_sse_event("done", {})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
