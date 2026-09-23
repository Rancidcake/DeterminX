"""2.11 Trend Intelligence — deterministic trend classification over the full
historical series for revenue, profit, margins, debt, and cash flow. Never an
LLM 'observation' — the same OLS-slope classifier V1 already uses for revenue
and balance-sheet trend direction (see `src/revenue_agent.py::classify_trend`).
"""

from __future__ import annotations

from typing import Any

from metrics import util
from metrics.schema import CATEGORY_TREND, Fact, unavailable

CATEGORY = CATEGORY_TREND

_TREND_FIELDS: dict[str, tuple[str, str]] = {
    "revenue_trend": ("revenue", "Revenue"),
    "profit_trend": ("net_income", "Net Income (PAT)"),
    "debt_trend": ("total_debt", "Total Debt"),
    "cash_flow_trend": ("operating_cash_flow", "Operating Cash Flow"),
}


def compute(payload: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []

    for metric, (field, label) in _TREND_FIELDS.items():
        periods = util.common_periods(payload, [field])
        if len(periods) < 3:
            facts.append(unavailable(
                metric=metric, category=CATEGORY,
                reason=f"Need at least 3 periods of '{field}' to classify a trend; found {len(periods)}.",
            ))
            continue
        values = util.aligned_values(payload, field, periods)
        direction = util.linear_trend_direction(values)
        facts.append(util.summary_fact(
            metric=metric, category=CATEGORY, value=direction, unit="label",
            formula=f"Sign/magnitude of OLS slope of {label} vs period index, normalised by mean {label}",
        ))

    # Margin trend — needs revenue + net_income to derive net margin per period
    nm_periods = util.common_periods(payload, ["revenue", "net_income"])
    if len(nm_periods) >= 3:
        rev = util.aligned_values(payload, "revenue", nm_periods)
        ni = util.aligned_values(payload, "net_income", nm_periods)
        margins = [n / r for n, r in zip(ni, rev) if r != 0]
        if len(margins) >= 3:
            direction = util.linear_trend_direction(margins)
            facts.append(util.summary_fact(
                metric="margin_trend", category=CATEGORY, value=direction, unit="label",
                formula="Sign/magnitude of OLS slope of Net Profit Margin (Net Income/Revenue) vs period index",
            ))
        else:
            facts.append(unavailable(metric="margin_trend", category=CATEGORY,
                                      reason="Revenue is zero in too many periods to compute a stable margin series."))
    else:
        facts.append(unavailable(
            metric="margin_trend", category=CATEGORY,
            reason="Need at least 3 periods with both 'revenue' and 'net_income'.",
        ))

    return facts
