"""A structlog JSON line is emitted for the compute run (counts/timings only)."""

import json
from datetime import date

from graph.runner import run_analysis

AS_OF = date(2026, 1, 15)


def test_compute_emits_structlog_json_line(capsys, small_xlsx_bytes, small_mapping):
    run_analysis(file_bytes=small_xlsx_bytes, sheet_name=None, mapping=small_mapping, as_of=AS_OF)
    out = capsys.readouterr().out

    events = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    computed = [e for e in events if e.get("event") == "metrics.computed"]
    assert computed, f"expected a metrics.computed JSON log line; got events: {[e.get('event') for e in events]}"
    evt = computed[0]
    assert evt["row_count"] == 18
    assert "duration_ms" in evt


def test_logs_never_contain_customer_data(capsys, small_xlsx_bytes, small_mapping):
    run_analysis(file_bytes=small_xlsx_bytes, sheet_name=None, mapping=small_mapping, as_of=AS_OF)
    out = capsys.readouterr().out
    # No customer names or balances leak into logs.
    for secret in ("Beacon", "Müller", "श्री", "3750000", "11175000"):
        assert secret not in out
