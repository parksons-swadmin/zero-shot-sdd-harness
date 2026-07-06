"""Built-in DEFAULT MAPPING PROFILE + the ``auto_mapped`` skip-confirm signal.

A recognized standard export whose headers exactly match the built-in profile
(canonical field -> exact source header) is resolved WITHOUT the fuzzy path and
flagged ``auto_mapped=True`` so the client can skip the mapping-confirm screen.
This is a stateless preset (no persistence).

Three-scenario coverage:
- happy path: exact profile headers -> every required field maps to its profile
  column at high status, invoice_date wins "Base Line Date" over the decoy
  date columns, hod maps to "HoD Name", auto_mapped=True;
- edge case: a profile header missing / an ambiguous duplicate column ->
  auto_mapped=False while fuzzy proposals are still returned;
- back-compat: the messy ``ar_small.xlsx`` headers behave exactly as before
  (its low-confidence due_date keeps auto_mapped=False -> confirm screen).

No LLM, no DB, no network — deterministic detection.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

from openpyxl import Workbook

from graph.runner import build_preview
from tools.header_detect import (
    CANONICAL_FIELDS,
    DEFAULT_MAPPING_PROFILE,
    DEFAULT_MAPPING_PROFILE_HOD,
    compute_auto_mapped,
    detect_mapping,
)

AS_OF = date(2026, 1, 15)

# The exact profile headers PLUS decoy date columns ("Billing Date" /
# "AR Posting Dt") that a fuzzy matcher would otherwise pick for invoice_date.
PROFILE_HEADERS = [
    "Payer Name",
    "Invoice No.",
    "Billing Date",       # decoy — must NOT win invoice_date
    "AR Posting Dt",      # decoy — must NOT win invoice_date
    "Base Line Date",     # the true invoice_date per the profile
    "Due Date",
    "Amount Due",
    "Current Employee",
    "HoD Name",
]


def _by_field(matches):
    return {m.field: m for m in matches}


# --------------------------------------------------------------------------- #
# (a) happy path — exact profile headers auto-map, profile beats fuzzy decoys
# --------------------------------------------------------------------------- #
def test_profile_headers_map_every_field_high_and_auto_mapped():
    matches = detect_mapping(PROFILE_HEADERS)
    by_field = _by_field(matches)

    for field, expected_col in DEFAULT_MAPPING_PROFILE.items():
        m = by_field[field]
        assert m.matched_column == expected_col, (field, m.matched_column)
        assert m.status == "high"
        assert m.confidence >= get_high_cutoff()

    # invoice_date resolves to "Base Line Date" even though "Billing Date" and
    # "AR Posting Dt" are present and would out-score it under pure fuzzy.
    assert by_field["invoice_date"].matched_column == "Base Line Date"

    # Optional hod resolves to the exact profile header at high status.
    assert by_field["hod"].matched_column == DEFAULT_MAPPING_PROFILE_HOD
    assert by_field["hod"].status == "high"

    # The skip-confirm signal fires for the recognized standard export.
    assert compute_auto_mapped(matches, PROFILE_HEADERS) is True


def test_profile_match_is_case_and_whitespace_insensitive_returns_actual_column():
    """A profile header present with different case / extra whitespace still
    matches, and the ACTUAL sheet column string is returned verbatim."""
    columns = [
        "  payer   name ",
        "INVOICE NO.",
        "base line date",
        "due date",
        "amount due",
        "current employee",
    ]
    matches = detect_mapping(columns)
    by_field = _by_field(matches)

    assert by_field["customer"].matched_column == "  payer   name "
    assert by_field["invoice_no"].matched_column == "INVOICE NO."
    assert by_field["invoice_date"].matched_column == "base line date"
    assert by_field["employee"].matched_column == "current employee"
    for field in CANONICAL_FIELDS:
        assert by_field[field].status == "high"
    assert compute_auto_mapped(matches, columns) is True


# --------------------------------------------------------------------------- #
# (b) edge cases — missing header / ambiguous column -> auto_mapped False
# --------------------------------------------------------------------------- #
def test_missing_one_profile_header_blocks_auto_map_but_still_proposes():
    """Drop the exact "Amount Due" header (replace with a vaguer "Amount")
    -> the profile no longer covers all six. Even though "Amount" fuzzy-matches
    amount at HIGH status, the signal is False (a recognized standard export must
    carry ALL profile headers), while proposals are still returned for every
    field so the confirm screen is fully usable."""
    columns = [
        "Payer Name",
        "Invoice No.",
        "Base Line Date",
        "Due Date",
        "Amount",  # NOT the exact profile header "Amount Due"
        "Current Employee",
    ]
    matches = detect_mapping(columns)
    by_field = _by_field(matches)

    # amount still proposed via fuzzy against "Amount", at high status.
    assert by_field["amount"].matched_column == "Amount"
    assert by_field["amount"].status == "high"
    # Every required field still has a proposal (the mapping screen is usable).
    assert all(by_field[f].matched_column for f in CANONICAL_FIELDS)
    # ...but the profile did not cover all six -> confirm screen (req 5).
    assert compute_auto_mapped(matches, columns) is False


def test_fuzzy_all_high_without_profile_is_not_auto_mapped():
    """Back-compat guard (req 5): a sheet whose columns fuzzy-match all six at
    HIGH but carries NONE of the profile headers must still show the confirm
    screen. Proves auto_mapped is profile-gated, not merely status-gated."""
    columns = ["customer", "invoice no", "invoice date", "due date", "amount", "employee"]
    matches = detect_mapping(columns)
    by_field = _by_field(matches)
    assert all(by_field[f].status == "high" for f in CANONICAL_FIELDS)
    assert compute_auto_mapped(matches, columns) is False


def test_ambiguous_column_sheet_is_not_auto_mapped():
    """A sheet with no profile headers and only vague columns cannot auto-map,
    yet proposals are still returned (fuzzy behaviour intact)."""
    columns = ["Some Name", "Random Notes", "Zzz"]
    matches = detect_mapping(columns)
    assert compute_auto_mapped(matches, columns) is False
    assert len(matches) >= 1  # proposals still emitted


def test_compute_auto_mapped_rejects_duplicate_column_across_six():
    """Even with all profile headers present, a matches list carrying a duplicate
    column across the six is rejected (guards a would-be false positive)."""
    from domain.mapping import FieldMatch

    cols = list(DEFAULT_MAPPING_PROFILE.values())  # all six profile headers
    p = DEFAULT_MAPPING_PROFILE
    matches = [
        FieldMatch(field="customer", matched_column=p["customer"], confidence=100, status="high"),
        # invoice_no duplicated onto customer's column -> invalid.
        FieldMatch(field="invoice_no", matched_column=p["customer"], confidence=100, status="high"),
        FieldMatch(field="invoice_date", matched_column=p["invoice_date"], confidence=100, status="high"),
        FieldMatch(field="due_date", matched_column=p["due_date"], confidence=100, status="high"),
        FieldMatch(field="amount", matched_column=p["amount"], confidence=100, status="high"),
        FieldMatch(field="employee", matched_column=p["employee"], confidence=100, status="high"),
    ]
    assert compute_auto_mapped(matches, cols) is False


def test_compute_auto_mapped_rejects_low_status_field():
    """All profile headers present but a matches entry is low status -> False."""
    from domain.mapping import FieldMatch

    cols = list(DEFAULT_MAPPING_PROFILE.values())
    p = DEFAULT_MAPPING_PROFILE
    matches = [
        FieldMatch(field="customer", matched_column=p["customer"], confidence=100, status="high"),
        FieldMatch(field="invoice_no", matched_column=p["invoice_no"], confidence=100, status="high"),
        FieldMatch(field="invoice_date", matched_column=p["invoice_date"], confidence=100, status="high"),
        FieldMatch(field="due_date", matched_column=p["due_date"], confidence=70, status="low"),
        FieldMatch(field="amount", matched_column=p["amount"], confidence=100, status="high"),
        FieldMatch(field="employee", matched_column=p["employee"], confidence=100, status="high"),
    ]
    assert compute_auto_mapped(matches, cols) is False


# --------------------------------------------------------------------------- #
# (c) back-compat — messy ar_small headers behave exactly as before
# --------------------------------------------------------------------------- #
def test_ar_small_headers_unchanged_auto_map_false(small_xlsx_bytes):
    """The committed messy fixture keeps its low-confidence due_date and thus
    the confirm-screen path: auto_mapped=False, fuzzy proposals unchanged."""
    preview = build_preview(file_bytes=small_xlsx_bytes)
    assert preview.auto_mapped is False

    by_field = _by_field(preview.proposed_mapping)
    # due_date stays low (the confirm-screen trigger from Phase 1).
    assert by_field["due_date"].status == "low"
    # The other five still fuzzy-match high, exactly as before the profile.
    for field in ("customer", "invoice_no", "invoice_date", "amount", "employee"):
        assert by_field[field].status == "high"


def test_no_profile_headers_behaves_like_pure_fuzzy():
    """A sheet with none of the profile headers is untouched by the profile —
    identical proposals to the historical fuzzy-only behaviour."""
    columns = ["Cust Name", "Invoice #", "Inv. Date", "Payable On", "Balance Outstanding", "Sales Person"]
    matches = detect_mapping(columns)
    by_field = _by_field(matches)
    assert by_field["customer"].matched_column == "Cust Name"
    assert by_field["due_date"].status == "low"
    assert "hod" not in by_field  # no plausible hod column, none proposed
    assert compute_auto_mapped(matches, columns) is False


# --------------------------------------------------------------------------- #
# End-to-end through build_preview with a recognized standard export workbook
# --------------------------------------------------------------------------- #
def _profile_workbook() -> bytes:
    """A workbook whose headers exactly match the default profile (+ decoys)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "AR"
    ws.append([
        "Payer Name", "Invoice No.", "Billing Date", "AR Posting Dt",
        "Base Line Date", "Due Date", "Amount Due", "Current Employee", "HoD Name",
    ])
    ws.append([
        "Acme Corp", "INV-1", date(2025, 1, 1), date(2025, 1, 2),
        date(2025, 1, 3), AS_OF - timedelta(days=40), 1000.0, "Ravi", "Alice",
    ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_build_preview_surfaces_auto_mapped_for_recognized_export():
    preview = build_preview(file_bytes=_profile_workbook())
    assert preview.auto_mapped is True
    by_field = _by_field(preview.proposed_mapping)
    assert by_field["invoice_date"].matched_column == "Base Line Date"
    assert by_field["customer"].matched_column == "Payer Name"
    assert by_field["employee"].matched_column == "Current Employee"
    assert by_field["hod"].matched_column == "HoD Name"


# --------------------------------------------------------------------------- #
# helper
# --------------------------------------------------------------------------- #
def get_high_cutoff() -> int:
    from config.settings import get_settings

    return get_settings().header_match_threshold
