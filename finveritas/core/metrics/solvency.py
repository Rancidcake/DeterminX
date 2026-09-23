"""2.5 Solvency Intelligence — D/E, D/A, equity ratio, leverage, interest coverage, net debt."""

from __future__ import annotations

from typing import Any

from metrics import util
from metrics.schema import CATEGORY_SOLVENCY, Fact, unavailable

CATEGORY = CATEGORY_SOLVENCY


def compute(payload: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []
    currency = str((payload.get("entity") or {}).get("currency") or "") or "currency"

    de_periods = util.common_periods(payload, ["total_liabilities", "equity"])
    if de_periods:
        tl = util.aligned_values(payload, "total_liabilities", de_periods)
        eq = util.aligned_values(payload, "equity", de_periods)
        de = [round(l / e, 3) if e != 0 else None for l, e in zip(tl, eq)]
        facts.extend(util.period_facts(
            metric="debt_to_equity", category=CATEGORY, periods=de_periods, values=de,
            unit="ratio", formula="Total Liabilities / Equity",
        ))
        facts.extend(util.period_facts(
            metric="financial_leverage", category=CATEGORY, periods=de_periods, values=de,
            unit="ratio", formula="Total Liabilities / Equity",
        ))
        er = [round(e / (l + e), 3) if (l + e) != 0 else None for l, e in zip(tl, eq)]
        facts.extend(util.period_facts(
            metric="equity_ratio", category=CATEGORY, periods=de_periods, values=er,
            unit="ratio", formula="Equity / (Total Liabilities + Equity)",
        ))
    else:
        for m in ("debt_to_equity", "financial_leverage", "equity_ratio"):
            facts.append(unavailable(metric=m, category=CATEGORY,
                                      reason="Requires 'total_liabilities' and 'equity'."))

    da_periods = util.common_periods(payload, ["total_debt", "total_assets"])
    if da_periods:
        td = util.aligned_values(payload, "total_debt", da_periods)
        ta = util.aligned_values(payload, "total_assets", da_periods)
        dta = [round(d / a, 3) if a != 0 else None for d, a in zip(td, ta)]
        facts.extend(util.period_facts(
            metric="debt_to_assets", category=CATEGORY, periods=da_periods, values=dta,
            unit="ratio", formula="Total Debt / Total Assets",
        ))
    else:
        facts.append(unavailable(metric="debt_to_assets", category=CATEGORY,
                                  reason="Requires 'total_debt' and 'total_assets'."))

    ic_periods = util.common_periods(payload, ["operating_income", "interest_expense"])
    if ic_periods:
        op_inc = util.aligned_values(payload, "operating_income", ic_periods)
        ie = util.aligned_values(payload, "interest_expense", ic_periods)
        ic = [round(o / i, 3) if i != 0 else None for o, i in zip(op_inc, ie)]
        facts.extend(util.period_facts(
            metric="interest_coverage", category=CATEGORY, periods=ic_periods, values=ic,
            unit="ratio", formula="Operating Income (EBIT) / Interest Expense",
        ))
    else:
        facts.append(unavailable(metric="interest_coverage", category=CATEGORY,
                                  reason="Requires 'operating_income' and 'interest_expense'."))

    nd_periods = util.common_periods(payload, ["total_debt", "cash_and_equivalents"])
    net_debt_vals: dict[str, float] = {}
    if nd_periods:
        td = util.aligned_values(payload, "total_debt", nd_periods)
        cash = util.aligned_values(payload, "cash_and_equivalents", nd_periods)
        nd = [d - c for d, c in zip(td, cash)]
        net_debt_vals = dict(zip(nd_periods, nd))
        facts.extend(util.period_facts(
            metric="net_debt", category=CATEGORY, periods=nd_periods, values=nd,
            unit=currency, formula="Total Debt - Cash & Equivalents",
        ))
    else:
        facts.append(unavailable(metric="net_debt", category=CATEGORY,
                                  reason="Requires 'total_debt' and 'cash_and_equivalents'."))

    ebitda_map = util.series_map(payload, "ebitda")
    if not ebitda_map:
        op_inc_map = util.series_map(payload, "operating_income")
        dep_map = util.series_map(payload, "depreciation")
        ebitda_map = {p: op_inc_map[p] + dep_map[p] for p in set(op_inc_map) & set(dep_map)}

    if net_debt_vals and ebitda_map:
        common = sorted(set(net_debt_vals) & set(ebitda_map), key=util.period_sort_key)
        ratio_periods, ratio_vals = [], []
        for p in common:
            if ebitda_map[p] != 0:
                ratio_periods.append(p)
                ratio_vals.append(round(net_debt_vals[p] / ebitda_map[p], 3))
        if ratio_periods:
            facts.extend(util.period_facts(
                metric="net_debt_to_ebitda", category=CATEGORY, periods=ratio_periods, values=ratio_vals,
                unit="ratio", formula="Net Debt / EBITDA",
            ))
        else:
            facts.append(unavailable(metric="net_debt_to_ebitda", category=CATEGORY,
                                      reason="EBITDA is zero in all overlapping periods."))
    else:
        facts.append(unavailable(
            metric="net_debt_to_ebitda", category=CATEGORY,
            reason="Requires Net Debt and EBITDA (or operating_income + depreciation) for overlapping periods.",
        ))

    return facts
