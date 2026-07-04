"""Rule-based riskiest-account flags.

Phase-1 stub: returns no flags. Phase 2 fills in the largest-90+ rules.
"""

from __future__ import annotations

import pandas as pd

from domain.quality import RiskFlag


def compute_risk_flags(df: pd.DataFrame) -> list[RiskFlag]:  # noqa: ARG001 - Phase-2 fills this in
    return []
