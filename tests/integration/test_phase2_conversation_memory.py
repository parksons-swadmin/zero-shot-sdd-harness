"""Real-Gemini, real-SQLite within-session conversation-memory test (Phase 2).

Proves the headline library-and-sessions capability that within-session memory
is actually wired to the agent's reasoning: a CONTEXT-DEPENDENT follow-up that
only makes sense given the prior turn is answered correctly.

The session asks a first question ("what is the total revenue?"), then a
follow-up whose subject is a bare pronoun ("now break that down by region") —
"that" refers to *revenue* from the prior turn. Without prior-turn context the
agent cannot know what to break down; with it, the answer must be a per-region
revenue breakdown. We assert the follow-up answer surfaces the per-region
figures, proving load_context fed the prior turn into compose_answer.
"""
import io

import pandas as pd
import pytest


def _upload_csv(api_client, csv_bytes: bytes, filename: str) -> str:
    resp = api_client.post("/datasets", files={"file": (filename, csv_bytes, "text/csv")})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["dataset_id"]


def _create_session(api_client, dataset_ids: list[str]) -> str:
    resp = api_client.post("/sessions", json={"dataset_ids": dataset_ids})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["session_id"]


def _csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def _normalize(text: str) -> str:
    return text.replace(",", "").replace("$", "").replace(" ", "").lower()


def _ask(api_client, session_id: str, question: str) -> dict:
    resp = api_client.post(f"/sessions/{session_id}/messages", json={"question": question})
    assert resp.status_code == 200, resp.text
    query_result = resp.json()["data"]["query_result"]
    assert query_result["status"] in ("completed", "partial"), query_result
    assert query_result["summary_text"]
    return query_result


@pytest.mark.usefixtures("_require_llm_key")
def test_context_dependent_followup_reuses_prior_turn(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None

    # Each region's revenue is distinct so a genuine per-region breakdown is
    # verifiable, while the totals are also exact.
    df = pd.DataFrame({
        "region": ["West", "East", "North", "South"],
        "revenue": [1000.0, 4000.0, 2000.0, 3000.0],
    })
    per_region = {r: v for r, v in zip(df["region"], df["revenue"])}
    total = round(df["revenue"].sum(), 2)  # 10000.0

    dataset_id = _upload_csv(api_client, _csv_bytes(df), "sales.csv")
    session_id = _create_session(api_client, [dataset_id])

    # Turn 1: establishes the subject ("revenue") in the conversation.
    first = _ask(api_client, session_id, "What is the total revenue?")
    assert _normalize(f"{total:,.2f}") in _normalize(first["summary_text"]) or \
        _normalize(str(round(total))) in _normalize(first["summary_text"]), first["summary_text"]

    # Turn 2: bare-pronoun follow-up — only answerable WITH prior-turn context.
    followup = _ask(api_client, session_id, "Now break that down by region.")
    normalized = _normalize(followup["summary_text"])

    # The follow-up must produce a per-region breakdown: at least the two
    # extreme regions' distinct revenue figures must appear, proving "that"
    # was resolved to revenue via the prior turn (not a clarification request
    # or an error). Values are compared in normalized form to tolerate
    # thousands separators / currency symbols / decimal formatting.
    def _value_variants(v: float) -> set[str]:
        return {
            _normalize(f"{v:,.2f}"),
            _normalize(f"{v:.1f}"),
            _normalize(str(round(v))),
        }

    for region in ("East", "West"):
        val = per_region[region]
        assert any(variant in normalized for variant in _value_variants(val)), (
            f"per-region revenue for {region} ({val}) not found in follow-up answer: "
            f"{followup['summary_text']}"
        )

    # A table artifact (if present) should also carry the multi-row breakdown,
    # not the single scalar total from turn 1.
    table = followup.get("table")
    if table and table.get("rows"):
        assert len(table["rows"]) >= 2, table
