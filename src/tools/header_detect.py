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

# Built-in DEFAULT MAPPING PROFILE — a stateless preset (no persistence) of the
# canonical field -> exact expected source header for a recognized standard
# export. When these EXACT headers are present in a sheet (matched case- and
# whitespace-insensitively), the profile assignment takes PRECEDENCE over fuzzy
# matching, so a recognized export can skip the mapping-confirm screen. This is
# critical for ``invoice_date`` -> "Base Line Date": in the standard export
# other date columns ("Billing Date" / "AR Posting Dt") would out-score it under
# pure fuzzy matching, so the exact-profile match must win. The optional 7th
# ``hod`` field is resolved the same way but never affects the six-field gate.
DEFAULT_MAPPING_PROFILE: dict[str, str] = {
    "customer": "Payer Name",
    "invoice_no": "Invoice No.",
    "invoice_date": "Base Line Date",
    "due_date": "Due Date",
    "amount": "Amount Due",
    "employee": "Current Employee",
}
DEFAULT_MAPPING_PROFILE_HOD: str = "HoD Name"

# Confidence assigned to an exact default-profile header match (a deterministic
# ceiling, always at/above any fuzzy threshold -> always "high").
_PROFILE_CONFIDENCE = 100

_LOW_CUTOFF = 60  # score < this -> unmatched


def _norm_header(header: str) -> str:
    """Case- and whitespace-insensitive header key.

    Lower-cases and collapses any run of whitespace to a single space (and trims
    ends), so "Base Line Date", "base line date", and " Base   Line  Date " all
    match the same profile header while the ACTUAL sheet column string is what we
    return to the caller.
    """
    return " ".join(str(header).split()).lower()


def _resolve_profile(columns: list[str]) -> dict[str, str]:
    """Resolve the DEFAULT MAPPING PROFILE (incl. optional ``hod``) against a
    sheet's actual columns, case- and whitespace-insensitively.

    Returns ``{field: actual column string from the sheet}`` for every profile
    field whose exact header is present. Fields with no profile header in the
    sheet are absent from the result (they fall back to fuzzy detection). The
    ACTUAL column string from the sheet is preserved verbatim.
    """
    by_norm: dict[str, str] = {}
    for col in columns:
        by_norm.setdefault(_norm_header(col), col)  # first occurrence wins

    resolved: dict[str, str] = {}
    profile = {**DEFAULT_MAPPING_PROFILE, "hod": DEFAULT_MAPPING_PROFILE_HOD}
    for field, expected in profile.items():
        actual = by_norm.get(_norm_header(expected))
        if actual is not None:
            resolved[field] = actual
    return resolved


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

    # Exact default-profile matches take PRECEDENCE over fuzzy detection.
    profile = _resolve_profile(columns)

    for field in CANONICAL_FIELDS:
        if field in profile:
            matches.append(
                FieldMatch(
                    field=field,
                    matched_column=profile[field],
                    confidence=_PROFILE_CONFIDENCE,
                    status="high",
                )
            )
            continue

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

    # Optional hod: an exact profile ("HoD Name") match wins; otherwise fall back
    # to fuzzy detection (emitted only when a plausible column exists).
    if "hod" in profile:
        matches.append(
            FieldMatch(
                field="hod",
                matched_column=profile["hod"],
                confidence=_PROFILE_CONFIDENCE,
                status="high",
            )
        )
    else:
        hod_match = _detect_hod(columns, threshold)
        if hod_match is not None:
            matches.append(hod_match)

    return matches


def compute_auto_mapped(matches: list[FieldMatch], columns: list[str]) -> bool:
    """True when the sheet is a recognized standard export needing no confirm.

    Fires only when the built-in DEFAULT MAPPING PROFILE resolves ALL SIX
    required canonical fields to DISTINCT columns present in the sheet, each at
    ``high`` status (with no duplicate column across the six). Gating on the
    profile — not merely on fuzzy ``high`` status — is what keeps the back-compat
    guarantee: a sheet WITHOUT the profile headers behaves exactly as before
    (``auto_mapped=False``, confirm screen), even if fuzzy happens to score all
    six high. The optional ``hod`` field never affects this.
    """
    profile = _resolve_profile(columns)
    if not all(field in profile for field in CANONICAL_FIELDS):
        return False

    # Profile coverage already guarantees six distinct present columns; verify
    # the emitted matches uphold req-3's high/distinct/no-duplicate invariant.
    available = set(columns)
    by_field = {m.field: m for m in matches}
    seen: set[str] = set()
    for field in CANONICAL_FIELDS:
        m = by_field.get(field)
        if m is None or m.status != "high" or m.matched_column is None:
            return False
        if m.matched_column not in available or m.matched_column in seen:
            return False
        seen.add(m.matched_column)

    return len(seen) == len(CANONICAL_FIELDS)


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
