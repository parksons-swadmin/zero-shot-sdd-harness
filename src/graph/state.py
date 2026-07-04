from datetime import date
from typing import TypedDict

import pandas as pd

from domain.aging import AgingMetrics
from domain.mapping import ColumnMapping
from domain.quality import QualityFlag, RiskFlag


class AnalysisState(TypedDict, total=False):
    # Identity
    run_id: str

    # Input (set by the runner from the request)
    file_bytes: bytes
    sheet_name: str | None
    mapping: ColumnMapping
    as_of: date
    phase: int

    # Optional pre-read raw frame — lets the runner read the workbook once
    # (for mapping validation) and hand it to node_ingest, avoiding a second
    # full read of large files. When absent, node_ingest reads file_bytes.
    raw_df: pd.DataFrame

    # Pipeline data (populated progressively by nodes)
    df: pd.DataFrame
    quality_flags: list[QualityFlag]
    risk_flags: list[RiskFlag]

    # Output
    metrics: AgingMetrics

    # Control
    error: str | None
