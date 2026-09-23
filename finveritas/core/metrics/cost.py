"""2.2 Cost Intelligence — COGS, opex, SG&A, R&D, depreciation, amortization."""

from __future__ import annotations

from typing import Any

from metrics import util
from metrics.schema import CATEGORY_COST, Fact, unavailable

CATEGORY = CATEGORY_COST

# metric -> (canonical field, human formula note)
_SIMPLE_FIELDS: dict[str, tuple[str, str]] = {
    "cost_of_revenue": ("cost_of_revenue", "As reported (COGS / cost of goods sold / cost of sales)"),
    "sga_expense": ("sga_expense", "As reported (selling, general & administrative expense)"),
    "rd_expense": ("rd_expense", "As reported (research & development expense)"),
    "depreciation": ("depreciation", "As reported (may include amortization if the statement does not split D&A)"),
    "amortization": ("amortization", "As reported, only when disclosed separately from depreciation"),
}


def compute(payload: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []
    currency = str((payload.get("entity") or {}).get("currency") or "") or "currency"

    for metric, (field, formula) in _SIMPLE_FIELDS.items():
        periods = util.common_periods(payload, [field])
        if not periods:
            facts.append(unavailable(
                metric=metric, category=CATEGORY,
                reason=f"No '{field}' time series present in ingested data.",
            ))
            continue
        values = util.aligned_values(payload, field, periods)
        facts.extend(util.period_facts(
            metric=metric, category=CATEGORY, periods=periods, values=values,
            unit=currency, formula=formula,
        ))

    # Operating Expenses = SG&A + R&D + D&A when available; otherwise derived
    # as Revenue - COGS - Operating Income when all three are present, else
    # unavailable (never guessed).
    op_periods = util.common_periods(payload, ["sga_expense", "rd_expense"])
    if op_periods:
        sga = util.aligned_values(payload, "sga_expense", op_periods)
        rd = util.aligned_values(payload, "rd_expense", op_periods)
        dep_map = util.series_map(payload, "depreciation")
        opex = []
        for i, p in enumerate(op_periods):
            total = sga[i] + rd[i] + dep_map.get(p, 0.0)
            opex.append(total)
        facts.extend(util.period_facts(
            metric="operating_expenses", category=CATEGORY, periods=op_periods, values=opex,
            unit=currency, formula="SG&A + R&D + Depreciation (only components actually present are summed)",
        ))
    else:
        derived_periods = util.common_periods(payload, ["revenue", "cost_of_revenue", "operating_income"])
        if derived_periods:
            rev = util.aligned_values(payload, "revenue", derived_periods)
            cogs = util.aligned_values(payload, "cost_of_revenue", derived_periods)
            op_inc = util.aligned_values(payload, "operating_income", derived_periods)
            opex = [r - c - o for r, c, o in zip(rev, cogs, op_inc)]
            facts.extend(util.period_facts(
                metric="operating_expenses", category=CATEGORY, periods=derived_periods, values=opex,
                unit=currency, formula="Revenue - Cost of Revenue - Operating Income (residual, derived)",
                status="ESTIMATED",
            ))
        else:
            facts.append(unavailable(
                metric="operating_expenses", category=CATEGORY,
                reason="Requires either SG&A+R&D, or revenue/cost_of_revenue/operating_income to derive as a residual.",
            ))

    return facts
