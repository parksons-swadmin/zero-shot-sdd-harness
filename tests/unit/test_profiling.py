import numpy as np
import pandas as pd

from tools.profiling import build_profile


def test_profile_numeric_and_categorical_columns_full_dataset_no_sampling():
    n = 5000
    rng = np.random.default_rng(42)
    revenue = rng.uniform(0, 1000, size=n)
    revenue[10] = np.nan  # one known null
    region = np.array(["West", "East", "North", "South"])[rng.integers(0, 4, size=n)]

    df = pd.DataFrame({"revenue": revenue, "region": region})

    profile = build_profile(df)
    by_name = {c["name"]: c for c in profile}

    revenue_col = by_name["revenue"]
    assert revenue_col["null_count"] == 1
    non_null = pd.Series(revenue).dropna()
    assert revenue_col["min"] == float(non_null.min())
    assert revenue_col["max"] == float(non_null.max())
    assert abs(revenue_col["mean"] - float(non_null.mean())) < 1e-9
    assert abs(revenue_col["median"] - float(non_null.median())) < 1e-9
    assert revenue_col["top_values"] is None
    assert revenue_col["distinct_count"] == df["revenue"].nunique(dropna=True)

    region_col = by_name["region"]
    assert region_col["null_count"] == 0
    assert region_col["distinct_count"] == 4
    assert region_col["min"] is None
    assert region_col["mean"] is None
    top_values = {tv["value"]: tv["count"] for tv in region_col["top_values"]}
    expected_counts = pd.Series(region).value_counts().to_dict()
    for value, count in top_values.items():
        assert expected_counts[value] == count


def test_profile_handles_empty_dataframe():
    df = pd.DataFrame({"a": pd.Series(dtype="float64"), "b": pd.Series(dtype="object")})
    profile = build_profile(df)
    by_name = {c["name"]: c for c in profile}
    assert by_name["a"]["null_count"] == 0
    assert by_name["a"]["min"] is None
    assert by_name["b"]["top_values"] == []


def test_profile_all_null_numeric_column_has_no_min_max():
    df = pd.DataFrame({"a": [np.nan, np.nan, np.nan]})
    profile = build_profile(df)
    col = profile[0]
    assert col["null_count"] == 3
    assert col["min"] is None
    assert col["max"] is None
    assert col["mean"] is None
