"""2.1 Revenue Intelligence — revenue, growth, CAGR, YoY.

`other_operating_income` / `revenue_from_operations` are not distinct
canonical fields in this codebase's ingestion schema (V1 collapses all
revenue-line variants into the single `revenue` field at parse time — see
`src/mapper.py`). We surface that explicitly rather than pretending a
breakdown exists.
"""

from __future__ import annotations

from typing import Any

from metrics import util
from metrics.schema import (
    CATEGORY_REVENUE, Fact, calculated, unavailable,
)

CATEGORY = CATEGORY_REVENUE


def compute(payload: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []
    periods = util.common_periods(payload, ["revenue"])

    if not periods:
        facts.append(unavailable(
            metric="revenue", category=CATEGORY,
            reason="No 'revenue' time series present in ingested data.",
        ))
        facts.append(unavailable(
            metric="revenue_growth", category=CATEGORY,
            reason="Requires 'revenue' time series.",
        ))
        facts.append(unavailable(
            metric="revenue_cagr", category=CATEGORY,
            reason="Requires 'revenue' time series.",
        ))
        return facts

    values = util.aligned_values(payload, "revenue", periods)
    currency = str((payload.get("entity") or {}).get("currency") or "")

    facts.extend(util.period_facts(
        metric="revenue", category=CATEGORY, periods=periods, values=values,
        unit=currency or "currency", formula="As reported (total_revenue / net_sales / revenue_from_operations, collapsed to a single canonical field at ingestion)",
    ))

    facts.append(unavailable(
        metric="net_sales", category=CATEGORY,
        reason="Not tracked as a field distinct from 'revenue' by the current ingestion schema.",
    ))
    facts.append(unavailable(
        metric="revenue_from_operations", category=CATEGORY,
        reason="Not tracked as a field distinct from 'revenue' by the current ingestion schema.",
    ))
    facts.append(unavailable(
        metric="other_operating_income", category=CATEGORY,
        reason="Not a separately ingested field.",
    ))

    growth = util.yoy_growth_pct(values)
    facts.extend(util.period_facts(
        metric="revenue_growth", category=CATEGORY, periods=periods, values=growth,
        unit="%", formula="(revenue[t] - revenue[t-1]) / |revenue[t-1]| * 100",
    ))

    yoy_vals = [g for g in growth if g is not None]
    if yoy_vals:
        facts.append(util.summary_fact(
            metric="revenue_yoy_growth_avg", category=CATEGORY,
            value=round(util.mean(yoy_vals), 2), unit="%",
            formula="mean(revenue_growth over all periods)",
        ))

    if len(values) >= 2 and values[0] > 0:
        years = len(values) - 1
        cagr = util.cagr_pct(values[0], values[-1], years)
        if cagr is not None:
            facts.append(util.summary_fact(
                metric="revenue_cagr", category=CATEGORY, value=round(cagr, 2), unit="%",
                formula=f"((revenue[{periods[-1]}] / revenue[{periods[0]}]) ^ (1/{years}) - 1) * 100",
            ))
        else:
            facts.append(unavailable(metric="revenue_cagr", category=CATEGORY,
                                      reason="Could not compute CAGR from available values."))
    else:
        facts.append(unavailable(
            metric="revenue_cagr", category=CATEGORY,
            reason="Need at least 2 periods with a positive first-period revenue value.",
        ))

    trend = util.linear_trend_direction(values)
    facts.append(util.summary_fact(
        metric="revenue_trend_direction", category=CATEGORY, value=trend, unit="label",
        formula="Sign/magnitude of OLS slope of revenue vs period index, normalised by mean revenue",
    ))

    return facts
