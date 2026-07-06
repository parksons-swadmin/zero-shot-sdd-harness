"""Rule-based riskiest-account flags.

Deterministic, no LLM: the riskiest accounts are the customers with the largest
``90+`` overdue balances. Only customers with a non-zero ``90+`` total qualify;
the top ``AGENT_RISK_TOP_N`` (default 5) are surfaced. Flags are advisory — they
never alter the computed totals.
"""

from __future__ import annotations

import pandas as pd

from config.settings import get_settings
from domain.quality import RiskFlag

_REASON = "largest 90+ overdue"
_BUCKET = "90+"


def compute_risk_flags(df: pd.DataFrame) -> list[RiskFlag]:
    """Riskiest accounts by total ``90+`` overdue amount, descending.

    Reads the real normalized frame: rows in the ``90+`` bucket with ``dpd > 0``.
    Ties broken by customer name ascending so the output is deterministic. The
    ``amount`` is the customer's ``90+`` total in rupees.
    """
    top_n = get_settings().risk_top_n

    overdue_90 = (df["bucket"] == "90+") & (df["dpd"] > 0).fillna(False)
    sub = df[overdue_90]
    if sub.empty:
        return []

    by_customer = (
        sub.groupby("customer", as_index=False)["amount_paise"].sum()
    )
    # Only customers with a non-zero 90+ balance qualify.
    by_customer = by_customer[by_customer["amount_paise"] != 0]
    if by_customer.empty:
        return []

    ranked = by_customer.sort_values(
        by=["amount_paise", "customer"], ascending=[False, True]
    ).head(top_n)

    return [
        RiskFlag(
            customer=str(r.customer),
            reason=_REASON,
            amount=round(int(r.amount_paise) / 100, 2),
            bucket=_BUCKET,
        )
        for r in ranked.itertuples(index=False)
    ]
