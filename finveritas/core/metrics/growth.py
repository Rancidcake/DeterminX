"""2.10 Growth Intelligence — YoY growth + multi-year CAGR for the key line items."""

from __future__ import annotations

from typing import Any

from metrics import util
from metrics.schema import CATEGORY_GROWTH, Fact, unavailable

CATEGORY = CATEGORY_GROWTH

# metric prefix -> canonical field (EBIT reuses operating_income, same as
# Profitability Intelligence's EBIT convention).
_FIELDS: dict[str, str] = {
    "revenue_growth": "revenue",
    "ebitda_growth": "ebitda",
    "pat_growth": "net_income",
    "ebit_growth": "operating_income",
    "asset_growth": "total_assets",
    "equity_growth": "equity",
    "cash_flow_growth": "operating_cash_flow",
}


def compute(payload: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []

    for metric, field in _FIELDS.items():
        periods = util.common_periods(payload, [field])
        if not periods:
            facts.append(unavailable(metric=metric, category=CATEGORY, reason=f"Requires '{field}'."))
            facts.append(unavailable(metric=f"{metric.rsplit('_', 1)[0]}_cagr", category=CATEGORY,
                                      reason=f"Requires '{field}'."))
            continue

        values = util.aligned_values(payload, field, periods)
        growth = util.yoy_growth_pct(values)
        facts.extend(util.period_facts(
            metric=metric, category=CATEGORY, periods=periods, values=growth,
            unit="%", formula=f"({field}[t] - {field}[t-1]) / |{field}[t-1]| * 100",
        ))

        base_name = metric.rsplit("_", 1)[0]  # e.g. "revenue" from "revenue_growth"
        cagr_metric = f"{base_name}_cagr"
        if len(values) >= 2 and values[0] > 0:
            years = len(values) - 1
            cagr = util.cagr_pct(values[0], values[-1], years)
            if cagr is not None:
                facts.append(util.summary_fact(
                    metric=cagr_metric, category=CATEGORY, value=round(cagr, 3), unit="%",
                    formula=f"(({field}[{periods[-1]}] / {field}[{periods[0]}]) ^ (1/{years}) - 1) * 100",
                ))
            else:
                facts.append(unavailable(metric=cagr_metric, category=CATEGORY,
                                          reason="Could not compute CAGR from available values."))
        else:
            facts.append(unavailable(
                metric=cagr_metric, category=CATEGORY,
                reason="Need at least 2 periods with a positive first-period value.",
            ))

    return facts
