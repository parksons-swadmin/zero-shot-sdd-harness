"""Fuzzy header detection: tiers, all-synonym, unmatched."""

from tools.header_detect import CANONICAL_FIELDS, SYNONYM_SEEDS, detect_mapping


def _by_field(matches):
    return {m.field: m for m in matches}


def test_messy_headers_five_high_one_low():
    """The ar_small headers: five high, due_date low (confirm path)."""
    columns = ["Cust Name", "Invoice #", "Inv. Date", "Payable On", "Balance Outstanding", "Sales Person"]
    matches = _by_field(detect_mapping(columns))

    assert matches["customer"].matched_column == "Cust Name" and matches["customer"].status == "high"
    assert matches["invoice_no"].matched_column == "Invoice #" and matches["invoice_no"].status == "high"
    assert matches["invoice_date"].matched_column == "Inv. Date" and matches["invoice_date"].status == "high"
    assert matches["amount"].matched_column == "Balance Outstanding" and matches["amount"].status == "high"
    assert matches["employee"].matched_column == "Sales Person" and matches["employee"].status == "high"

    due = matches["due_date"]
    assert due.matched_column == "Payable On"
    assert due.status == "low"
    assert 60 <= due.confidence < 85


def test_all_synonym_headers_all_high():
    columns = [SYNONYM_SEEDS[f][0] for f in CANONICAL_FIELDS]
    matches = _by_field(detect_mapping(columns))
    for field in CANONICAL_FIELDS:
        assert matches[field].status == "high"
        assert matches[field].confidence >= 85


def test_unrecognisable_header_is_unmatched():
    """A file whose customer column is missing/unrecognisable: no present column
    scores >= 60 for `customer`, so it is unmatched (compute blocked until the
    user supplies it) while other fields still match."""
    columns = ["Zzz Notes", "Invoice #", "Sales Person"]
    matches = _by_field(detect_mapping(columns))

    assert matches["customer"].status == "unmatched"
    assert matches["customer"].matched_column is None
    assert matches["customer"].confidence < 60
    # other fields still resolve, proving only the one field is unmatched
    assert matches["invoice_no"].status == "high"
    assert matches["employee"].status == "high"


def test_threshold_is_configurable(monkeypatch):
    """Raising the threshold demotes a borderline-high match to low."""
    monkeypatch.setenv("AGENT_HEADER_MATCH_THRESHOLD", "96")
    import config.settings as m

    m._settings = None
    columns = ["Cust Name", "Invoice #", "Inv. Date", "Payable On", "Balance Outstanding", "Sales Person"]
    matches = _by_field(detect_mapping(columns))
    # customer scored ~90 < 96 now -> low
    assert matches["customer"].status == "low"
