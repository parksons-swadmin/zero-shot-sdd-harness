import numpy as np
import pandas as pd

from tools.cleaning import clean_dataset


def test_cleaning_fixes_whitespace_dates_and_currency_and_reports_issues():
    df = pd.DataFrame(
        {
            "name": [" Alice ", "Bob", " Carol", "Dave "],
            "signup_date": ["2024-01-05", "01/06/2024", "2024-01-07", "01/08/2024"],
            "revenue": ["$1,000.50", "2,000", "$500", "750.25"],
        }
    )
    cleaned, issues = clean_dataset(df)

    # whitespace stripped
    assert list(cleaned["name"]) == ["Alice", "Bob", "Carol", "Dave"]
    whitespace_issue = next(i for i in issues if i["issue_type"] == "leading_trailing_whitespace")
    assert whitespace_issue["column"] == "name"
    assert whitespace_issue["affected_row_count"] == 3
    assert whitespace_issue["needs_review"] is False

    # dates parsed to ISO-8601
    assert all(str(v).count("-") == 2 for v in cleaned["signup_date"])
    date_issue = next(i for i in issues if i["issue_type"] == "inconsistent_format")
    assert date_issue["column"] == "signup_date"
    assert date_issue["needs_review"] is False

    # currency coerced to numeric
    assert pd.api.types.is_numeric_dtype(cleaned["revenue"])
    assert cleaned["revenue"].iloc[0] == 1000.50
    numeric_issue = next(i for i in issues if i["issue_type"] == "non_numeric_characters")
    assert numeric_issue["column"] == "revenue"
    assert numeric_issue["needs_review"] is False


def test_cleaning_flags_ambiguous_phone_format_without_guessing():
    df = pd.DataFrame(
        {
            "phone": ["+14155551234", "04155551234", "4155551234", "+442071838750"],
        }
    )
    cleaned, issues = clean_dataset(df)

    phone_issue = next(i for i in issues if i["issue_type"] == "ambiguous_country_code")
    assert phone_issue["column"] == "phone"
    assert phone_issue["action_taken"] == "left as-is"
    assert phone_issue["needs_review"] is True
    # left as-is: values unchanged
    assert list(cleaned["phone"]) == list(df["phone"])


def test_cleaning_drops_exact_duplicate_rows_and_reports_it():
    df = pd.DataFrame(
        {
            "a": [1, 2, 2, 3],
            "b": ["x", "y", "y", "z"],
        }
    )
    cleaned, issues = clean_dataset(df)

    assert len(cleaned) == 3
    dup_issue = next(i for i in issues if i["issue_type"] == "duplicate_rows")
    assert dup_issue["affected_row_count"] == 1
    assert dup_issue["needs_review"] is False


def test_cleaning_empty_dataframe_returns_no_issues():
    df = pd.DataFrame({"a": [], "b": []})
    cleaned, issues = clean_dataset(df)
    assert len(cleaned) == 0
    assert issues == []
