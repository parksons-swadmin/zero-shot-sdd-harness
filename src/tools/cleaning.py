"""Auto-cleaning of an uploaded dataset.

Runs against the FULL dataframe (never a sample). Detects and fixes realistic
CSV issues, always recording what was done in a report shaped per
spec/data.md -> CleaningReport.issues_json:
    {column, issue_type, action_taken, affected_row_count, needs_review}

Ambiguous cases take a documented default action and are flagged
needs_review=True rather than silently guessed.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

def _is_stringlike_column(s: pd.Series) -> bool:
    """True for object/string-dtype columns (pandas 2.x uses `object`,
    pandas 3.x defaults new string columns to a dedicated `str` dtype)."""
    return s.dtype == object or pd.api.types.is_string_dtype(s)


_CURRENCY_RE = re.compile(r"[$€£,]")
_NUMERIC_LIKE_RE = re.compile(r"^\s*[$€£]?\s*-?[\d,]+(\.\d+)?\s*%?\s*$")
_PHONE_NAME_RE = re.compile(r"phone|mobile|contact_number|tel", re.IGNORECASE)
_DATE_NAME_RE = re.compile(r"date|_at$|timestamp|time$", re.IGNORECASE)


def _is_numeric_like_series(s: pd.Series) -> bool:
    non_null = s.dropna().astype(str)
    if len(non_null) == 0:
        return False
    matches = non_null.str.match(_NUMERIC_LIKE_RE)
    return matches.mean() >= 0.9


def _strip_whitespace(df: pd.DataFrame, issues: list[dict]) -> None:
    for col in df.columns:
        if not _is_stringlike_column(df[col]):
            continue
        s = df[col]
        non_null_mask = s.notna()
        if non_null_mask.sum() == 0:
            continue
        as_str = s[non_null_mask].astype(str)
        stripped = as_str.str.strip()
        changed_mask = as_str != stripped
        affected = int(changed_mask.sum())
        if affected > 0:
            df.loc[non_null_mask, col] = stripped
            issues.append(
                {
                    "column": col,
                    "issue_type": "leading_trailing_whitespace",
                    "action_taken": "stripped surrounding whitespace",
                    "affected_row_count": affected,
                    "needs_review": False,
                }
            )


def _coerce_numeric_strings(df: pd.DataFrame, issues: list[dict]) -> None:
    for col in df.columns:
        if not _is_stringlike_column(df[col]):
            continue
        s = df[col]
        non_null_mask = s.notna()
        non_null = s[non_null_mask]
        if len(non_null) == 0:
            continue
        if not _is_numeric_like_series(s):
            continue
        as_str = non_null.astype(str)
        cleaned = (
            as_str.str.replace(_CURRENCY_RE, "", regex=True)
            .str.replace("%", "", regex=False)
            .str.strip()
        )
        numeric = pd.to_numeric(cleaned, errors="coerce")
        if numeric.notna().mean() < 0.9:
            continue
        changed_mask = as_str != cleaned
        affected = int(changed_mask.sum())
        new_col = pd.Series(np.nan, index=s.index, dtype="float64")
        new_col.loc[non_null_mask] = numeric.values
        df[col] = new_col
        if affected > 0:
            issues.append(
                {
                    "column": col,
                    "issue_type": "non_numeric_characters",
                    "action_taken": "stripped currency/percent symbols and coerced to numeric",
                    "affected_row_count": affected,
                    "needs_review": False,
                }
            )


def _parse_dates(df: pd.DataFrame, issues: list[dict]) -> None:
    for col in df.columns:
        if not _is_stringlike_column(df[col]):
            continue
        if not _DATE_NAME_RE.search(col):
            continue
        s = df[col]
        non_null_mask = s.notna()
        if non_null_mask.sum() == 0:
            continue
        raw = s[non_null_mask].astype(str)
        parsed = pd.to_datetime(raw, errors="coerce", format="mixed")
        success_rate = parsed.notna().mean()
        if success_rate < 0.8:
            continue
        iso = parsed.dt.strftime("%Y-%m-%d")
        changed = raw.reset_index(drop=True) != iso.reset_index(drop=True)
        affected = int(changed.sum())
        new_col = s.copy()
        new_col.loc[non_null_mask] = iso.values
        df[col] = new_col
        if affected > 0:
            issues.append(
                {
                    "column": col,
                    "issue_type": "inconsistent_format",
                    "action_taken": "parsed to ISO-8601",
                    "affected_row_count": affected,
                    "needs_review": False,
                }
            )
        unparsed = int(parsed.isna().sum())
        if unparsed > 0:
            issues.append(
                {
                    "column": col,
                    "issue_type": "unparseable_date",
                    "action_taken": "left as-is (could not parse)",
                    "affected_row_count": unparsed,
                    "needs_review": True,
                }
            )


def _flag_ambiguous_phone_formats(df: pd.DataFrame, issues: list[dict]) -> None:
    for col in df.columns:
        if not _PHONE_NAME_RE.search(col):
            continue
        s = df[col].dropna().astype(str)
        if len(s) == 0:
            continue
        has_plus = s.str.startswith("+")
        has_leading_zero = s.str.match(r"^0\d+")
        bare_digits = s.str.match(r"^\d{7,}$")
        variants = sum([has_plus.any(), has_leading_zero.any(), bare_digits.any()])
        if variants >= 2:
            affected = int((has_plus | has_leading_zero | bare_digits).sum())
            issues.append(
                {
                    "column": col,
                    "issue_type": "ambiguous_country_code",
                    "action_taken": "left as-is",
                    "affected_row_count": affected,
                    "needs_review": True,
                }
            )


def _flag_exact_duplicates(df: pd.DataFrame, issues: list[dict]) -> pd.DataFrame:
    dup_mask = df.duplicated(keep="first")
    affected = int(dup_mask.sum())
    if affected > 0:
        df = df.loc[~dup_mask].reset_index(drop=True)
        issues.append(
            {
                "column": "*",
                "issue_type": "duplicate_rows",
                "action_taken": "dropped exact duplicate rows",
                "affected_row_count": affected,
                "needs_review": False,
            }
        )
    return df


def clean_dataset(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Auto-clean the full dataframe. Returns (cleaned_df, issues list).

    issues entries match spec/data.md CleaningReport.issues_json shape.
    """
    df = df.copy()
    issues: list[dict] = []

    _strip_whitespace(df, issues)
    _parse_dates(df, issues)
    _coerce_numeric_strings(df, issues)
    _flag_ambiguous_phone_formats(df, issues)
    df = _flag_exact_duplicates(df, issues)

    return df, issues
