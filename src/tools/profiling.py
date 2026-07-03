"""Full-dataset profiling — never sampled.

Produces the per-column aggregate shape defined in spec/data.md ->
DatasetProfile.columns_json: {name, dtype, null_count, distinct_count,
min, max, mean, median, top_values}. Only aggregates are ever computed here —
no raw row values are included in the output.
"""
from __future__ import annotations

import math

import pandas as pd


def _clean_float(value) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _top_values(s: pd.Series, top_n: int = 5) -> list[dict]:
    counts = s.dropna().astype(str).value_counts().head(top_n)
    return [{"value": str(v), "count": int(c)} for v, c in counts.items()]


def build_profile(df: pd.DataFrame) -> list[dict]:
    """Compute full-dataset per-column aggregates. Returns a list of column
    profile dicts (never a sample of rows, always the entire dataframe).
    """
    columns: list[dict] = []
    for col in df.columns:
        s = df[col]
        dtype = str(s.dtype)
        null_count = int(s.isna().sum())
        distinct_count = int(s.nunique(dropna=True))

        is_numeric = pd.api.types.is_numeric_dtype(s)
        if is_numeric:
            non_null = s.dropna()
            columns.append(
                {
                    "name": col,
                    "dtype": dtype,
                    "null_count": null_count,
                    "distinct_count": distinct_count,
                    "min": _clean_float(non_null.min()) if len(non_null) else None,
                    "max": _clean_float(non_null.max()) if len(non_null) else None,
                    "mean": _clean_float(non_null.mean()) if len(non_null) else None,
                    "median": _clean_float(non_null.median()) if len(non_null) else None,
                    "top_values": None,
                }
            )
        else:
            columns.append(
                {
                    "name": col,
                    "dtype": dtype,
                    "null_count": null_count,
                    "distinct_count": distinct_count,
                    "min": None,
                    "max": None,
                    "mean": None,
                    "median": None,
                    "top_values": _top_values(s),
                }
            )
    return columns
