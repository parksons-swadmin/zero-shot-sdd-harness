"""Real-Gemini, real-SQLite Phase-3a rich-artifacts test.

Proves the headline Phase-3a capability end to end against the real model:

1. A ranked "total revenue by region" question yields a `table` with exactly
   the 5 pre-computed per-region totals AND a `chart_spec` whose `series` is
   drawn from those aggregates and capped to `chart_max_points` (never 10,000).
2. An "export the West-region rows as a dataset" question yields a non-null
   `export_dataset_id`, the derived Dataset shows up in `GET /datasets`, and the
   exported file's row count equals the FULL West-region row count (not capped
   to the 200-row result cap) — proving the export is uncapped while the
   chart/table stay capped.
3. RAW-DATA boundary: a spy over every prompt string passed to
   `LLMClient.call_model_with_usage` asserts no raw fixture row value ever
   reaches the model — only aggregate profile fields + capped structured
   results — and that the chart series stays within the cap.
"""
import io

import pandas as pd
import pytest

from llm.client import LLMClient

# A distinctive sentinel that lives in exactly one EAST row (never West, never an
# aggregate, never a profile top-value since it is drowned out by the shared
# "note_*" memos). If it ever appears in a prompt, a raw row leaked.
_SENTINEL_MEMO = "SENTINEL_ZZZ_DO_NOT_LEAK_42"


def _build_fixture() -> tuple[pd.DataFrame, dict]:
    """10,000 rows, 5 regions with exact per-region revenue totals."""
    regions = ["West", "East", "North", "South", "Central"]
    per_region_revenue = {"West": 10.0, "East": 20.0, "North": 30.0, "South": 40.0, "Central": 50.0}
    rows_per_region = 2000  # 5 * 2000 = 10,000 rows

    records = []
    for region in regions:
        for i in range(rows_per_region):
            records.append({
                "region": region,
                "revenue": per_region_revenue[region],
                "memo": f"note_{i % 50}",
                "row_uid": len(records),
            })
    df = pd.DataFrame(records)

    # Plant the sentinel in one East row's memo (East, so it never appears in a
    # West-region export/capped result).
    east_idx = df.index[df["region"] == "East"][0]
    df.loc[east_idx, "memo"] = _SENTINEL_MEMO

    expected_totals = {r: round(per_region_revenue[r] * rows_per_region, 2) for r in regions}
    west_row_count = int((df["region"] == "West").sum())
    return df, {"expected_totals": expected_totals, "west_row_count": west_row_count}


def _csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def _upload_csv(api_client, csv_bytes: bytes, filename: str) -> str:
    resp = api_client.post("/datasets", files={"file": (filename, csv_bytes, "text/csv")})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["dataset_id"]


def _create_session(api_client, dataset_ids: list[str]) -> str:
    resp = api_client.post("/sessions", json={"dataset_ids": dataset_ids})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["session_id"]


def _ask(api_client, session_id: str, question: str) -> dict:
    resp = api_client.post(f"/sessions/{session_id}/messages", json={"question": question})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["query_result"]


@pytest.fixture
def _prompt_spy(monkeypatch):
    """Record every prompt+system string sent to the model, then delegate to
    the real call so the model still runs for real."""
    seen: list[str] = []
    original = LLMClient.call_model_with_usage

    def _spy(self, prompt, *args, **kwargs):
        seen.append(prompt)
        system = kwargs.get("system")
        if isinstance(system, str):
            seen.append(system)
        return original(self, prompt, *args, **kwargs)

    monkeypatch.setattr(LLMClient, "call_model_with_usage", _spy)
    return seen


@pytest.mark.usefixtures("_require_llm_key")
def test_phase3a_artifacts_and_export(api_client, tmp_path, monkeypatch, _prompt_spy):
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    import config.settings as settings_module
    settings_module._settings = None
    from config.settings import get_settings
    chart_cap = get_settings().chart_max_points

    df, meta = _build_fixture()
    dataset_id = _upload_csv(api_client, _csv_bytes(df), "sales.csv")
    session_id = _create_session(api_client, [dataset_id])

    # --- 1. Ranked table + capped chart from aggregates ------------------- #
    qr = _ask(api_client, session_id, "Show me total revenue by region, ranked from highest to lowest.")
    assert qr["status"] in ("completed", "partial"), qr

    table = qr["table"]
    assert table is not None, f"expected a table, got none: {qr}"
    assert len(table["rows"]) == 5, table

    # Every pre-computed per-region total must appear among the table's numeric
    # cells (column order/name is the model's choice, so scan all cells).
    numeric_cells = set()
    for row in table["rows"]:
        for cell in row:
            try:
                numeric_cells.add(round(float(cell), 2))
            except (TypeError, ValueError):
                continue
    for region, total in meta["expected_totals"].items():
        assert total in numeric_cells, f"{region} total {total} missing from table cells {numeric_cells}"

    chart = qr["chart_spec"]
    assert chart is not None, f"expected a chart, got none: {qr}"
    assert len(chart["series"]) <= chart_cap, chart
    assert len(chart["series"]) == 5, chart  # 5 aggregated points, not 10,000

    # --- 2. Full uncapped export -> derived Dataset in the library -------- #
    qr2 = _ask(api_client, session_id, "Export the rows for the West region as a dataset.")
    assert qr2["status"] in ("completed", "partial"), qr2
    export_dataset_id = qr2["export_dataset_id"]
    assert export_dataset_id, f"expected a non-null export_dataset_id: {qr2}"

    listing = api_client.get("/datasets")
    assert listing.status_code == 200, listing.text
    items = {d["dataset_id"]: d for d in listing.json()["data"]["datasets"]}
    assert export_dataset_id in items, f"derived dataset not in library: {list(items)}"

    derived_row_count = items[export_dataset_id]["row_count"]
    assert derived_row_count == meta["west_row_count"], (
        f"export row count {derived_row_count} != full West rows {meta['west_row_count']} "
        "(export must NOT be capped to the 200-row result cap)"
    )
    assert derived_row_count > 200, "export must exceed the result cap to prove it is uncapped"

    # --- 3. RAW-DATA boundary: no raw row value ever reached the model ---- #
    assert _prompt_spy, "no prompts were captured — spy misconfigured"
    for prompt in _prompt_spy:
        assert _SENTINEL_MEMO not in prompt, "a raw fixture row value leaked into an LLM prompt"
