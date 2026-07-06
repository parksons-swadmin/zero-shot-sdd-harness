"""Shared test fixtures.

The tool is stateless, no-LLM, no-DB: fixtures reset the settings singleton,
pin a fixed ``as_of`` date so aging buckets never go stale, and expose the
paths to the generated fixture workbooks/oracles.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIXTURES_DIR))

import build_fixtures as bf  # noqa: E402  (fixtures dir added to path above)

AS_OF = date(2026, 1, 15)


@pytest.fixture(autouse=True)
def _reset_settings_singleton():
    """Reset cached settings so env patches take effect in every test."""
    import config.settings as m

    m._settings = None
    yield
    m._settings = None


@pytest.fixture
def as_of() -> date:
    """The fixed reference date the fixtures are anchored to."""
    return AS_OF


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def ar_small_path() -> Path:
    return FIXTURES_DIR / "ar_small.xlsx"


@pytest.fixture
def small_xlsx_bytes() -> bytes:
    return (FIXTURES_DIR / "ar_small.xlsx").read_bytes()


@pytest.fixture
def small_mapping():
    from domain.mapping import ColumnMapping

    return ColumnMapping(
        customer="Cust Name",
        invoice_no="Invoice #",
        invoice_date="Inv. Date",
        due_date="Payable On",
        amount="Balance Outstanding",
        employee="Sales Person",
    )


@pytest.fixture
def expected_small() -> dict:
    import json

    return json.loads((FIXTURES_DIR / "expected_small.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def large_fixture(tmp_path_factory) -> dict:
    """Build the >=60,000-row fixture once per session into a tmp path.

    The multi-MB binary is NOT committed: it is generated here with a seeded
    RNG (reproducible), with high-value overdue rows in the LAST 100 so any
    truncating impl produces a wrong total. Expected values are an independent
    ``sum(round(a*100))`` oracle (see build_fixtures.compute_expected).
    """
    from domain.mapping import ColumnMapping

    path = tmp_path_factory.mktemp("large") / "ar_large.xlsx"
    expected = bf.build_large(path, n=60000, seed=12345)
    mapping = ColumnMapping(
        customer="Customer",
        invoice_no="Invoice No",
        invoice_date="Invoice Date",
        due_date="Due Date",
        amount="Amount",
        employee="Employee",
    )
    return {"path": path, "bytes": path.read_bytes(), "expected": expected, "mapping": mapping}
