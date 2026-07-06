"""Deterministic fuzzy header detection for the six canonical AR fields.

Uses rapidfuzz to score each source column header against per-field synonym
seeds and picks the best-matching column per field. The score is rapidfuzz's
general-purpose ``WRatio`` (a weighted composite that handles multi-word and
abbreviated headers such as ``Cust Name`` / ``Balance Outstanding`` which the
plain ``token_sort_ratio`` under-scores). Fully deterministic.
"""

from rapidfuzz import fuzz

from config.settings import get_settings
from domain.mapping import FieldMatch

# Canonical field -> synonym seeds (verbatim from
# spec/capabilities/xlsx_ingestion_and_mapping.md).
SYNONYM_SEEDS: dict[str, list[str]] = {
    "customer": ["customer", "cust", "party", "account name", "client", "buyer", "name"],
    "invoice_no": ["invoice no", "invoice #", "inv no", "bill no", "document no", "voucher"],
    "invoice_date": ["invoice date", "inv date", "bill date", "doc date", "date"],
    "due_date": ["due date", "due dt", "maturity date", "net due", "payable by"],
    "amount": ["amount", "balance", "outstanding", "amt", "net amount", "due amount", "pending"],
    "employee": [
        "employee",
        "salesperson",
        "sales person",
        "executive",
        "rep",
        "owner",
        "marketing person",
    ],
}

CANONICAL_FIELDS: list[str] = list(SYNONYM_SEEDS.keys())

# Optional 7th field — kept OUT of CANONICAL_FIELDS so it never gates the
# "all required mapped" check. The bare "hod name" seed is intentionally
# omitted: its "name" token false-matches unrelated "* Name" columns (e.g.
# "Cust Name" / "Payer Name"); the "hod" seed already matches "HoD Name" at a
# high score, so this keeps the standard 60 cutoff clean.
HOD_SYNONYM_SEEDS: list[str] = ["hod", "head of department", "department head", "reporting manager"]

_LOW_CUTOFF = 60  # score < this -> unmatched


def _best_against(header: str, seeds: list[str]) -> int:
    """Best WRatio score of a header against a list of synonym seeds (0-100)."""
    header_l = header.lower()
    return round(max(fuzz.WRatio(header_l, seed.lower()) for seed in seeds))


def _best_score(header: str, field: str) -> int:
    """Best WRatio score of a header against a canonical field's seeds (0-100)."""
    return _best_against(header, SYNONYM_SEEDS[field])


def detect_mapping(columns: list[str]) -> list[FieldMatch]:
    """Propose a source column for each of the six canonical fields.

    For every field, the source column with the highest fuzzy score wins. The
    confidence tier is derived from the high-confidence threshold
    (``AGENT_HEADER_MATCH_THRESHOLD``, default 85):

    - ``high``       score >= threshold
    - ``low``        60 <= score < threshold
    - ``unmatched``  score < 60
    """
    threshold = get_settings().header_match_threshold
    matches: list[FieldMatch] = []

    for field in CANONICAL_FIELDS:
        best_col: str | None = None
        best_score = -1
        for col in columns:
            score = _best_score(col, field)
            if score > best_score:
                best_score = score
                best_col = col

        if best_col is None or best_score < _LOW_CUTOFF:
            matches.append(
                FieldMatch(field=field, matched_column=None, confidence=max(best_score, 0), status="unmatched")
            )
        elif best_score >= threshold:
            matches.append(
                FieldMatch(field=field, matched_column=best_col, confidence=best_score, status="high")
            )
        else:
            matches.append(
                FieldMatch(field=field, matched_column=best_col, confidence=best_score, status="low")
            )

    hod_match = _detect_hod(columns, threshold)
    if hod_match is not None:
        matches.append(hod_match)

    return matches


def _detect_hod(columns: list[str], threshold: int) -> FieldMatch | None:
    """Propose an OPTIONAL ``hod`` column, or ``None`` when no plausible column.

    Fully separate from the six required canonical fields: it is emitted only
    when a column scores at or above the low cutoff, and its presence never
    affects the "all six required mapped" gate. A ``low`` proposal is fine — the
    user confirms/corrects it and it never blocks compute.
    """
    best_col: str | None = None
    best_score = -1
    for col in columns:
        score = _best_against(col, HOD_SYNONYM_SEEDS)
        if score > best_score:
            best_score = score
            best_col = col

    if best_col is None or best_score < _LOW_CUTOFF:
        return None

    status = "high" if best_score >= threshold else "low"
    return FieldMatch(field="hod", matched_column=best_col, confidence=best_score, status=status)
