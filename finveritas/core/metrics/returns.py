"""2.8 Return Intelligence — ROE, ROA, ROCE, ROIC."""

from __future__ import annotations

from typing import Any

from metrics import util
from metrics.schema import CATEGORY_RETURNS, Fact, unavailable

CATEGORY = CATEGORY_RETURNS


def compute(payload: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []

    roe_periods = util.common_periods(payload, ["net_income", "equity"])
    if roe_periods:
        ni = util.aligned_values(payload, "net_income", roe_periods)
        eq = util.aligned_values(payload, "equity", roe_periods)
        vals = [round(n / e, 4) * 100 if e != 0 else None for n, e in zip(ni, eq)]
        vals = [round(v, 3) if v is not None else None for v in vals]
        facts.extend(util.period_facts(
            metric="roe", category=CATEGORY, periods=roe_periods, values=vals,
            unit="%", formula="Net Income / Equity * 100",
        ))
    else:
        facts.append(unavailable(metric="roe", category=CATEGORY, reason="Requires 'net_income' and 'equity'."))

    roa_periods = util.common_periods(payload, ["net_income", "total_assets"])
    if roa_periods:
        ni = util.aligned_values(payload, "net_income", roa_periods)
        ta = util.aligned_values(payload, "total_assets", roa_periods)
        vals = [round(n / a * 100, 3) if a != 0 else None for n, a in zip(ni, ta)]
        facts.extend(util.period_facts(
            metric="roa", category=CATEGORY, periods=roa_periods, values=vals,
            unit="%", formula="Net Income / Total Assets * 100",
        ))
    else:
        facts.append(unavailable(metric="roa", category=CATEGORY, reason="Requires 'net_income' and 'total_assets'."))

    roce_periods = util.common_periods(payload, ["operating_income", "total_assets", "current_liabilities"])
    if roce_periods:
        op_inc = util.aligned_values(payload, "operating_income", roce_periods)
        ta = util.aligned_values(payload, "total_assets", roce_periods)
        cl = util.aligned_values(payload, "current_liabilities", roce_periods)
        vals, out_p = [], []
        for p, o, a, l in zip(roce_periods, op_inc, ta, cl):
            capital_employed = a - l
            if capital_employed:
                out_p.append(p)
                vals.append(round(o / capital_employed * 100, 3))
        if out_p:
            facts.extend(util.period_facts(
                metric="roce", category=CATEGORY, periods=out_p, values=vals,
                unit="%", formula="Operating Income (EBIT) / (Total Assets - Current Liabilities) * 100",
            ))
        else:
            facts.append(unavailable(metric="roce", category=CATEGORY,
                                      reason="Capital employed is zero in all overlapping periods."))
    else:
        facts.append(unavailable(metric="roce", category=CATEGORY,
                                  reason="Requires 'operating_income', 'total_assets', 'current_liabilities'."))

    roic_periods = util.common_periods(
        payload, ["operating_income", "income_tax", "pretax_income", "total_debt", "equity", "cash_and_equivalents"]
    )
    if roic_periods:
        op_inc = util.aligned_values(payload, "operating_income", roic_periods)
        tax = util.aligned_values(payload, "income_tax", roic_periods)
        pretax = util.aligned_values(payload, "pretax_income", roic_periods)
        debt = util.aligned_values(payload, "total_debt", roic_periods)
        eq = util.aligned_values(payload, "equity", roic_periods)
        cash = util.aligned_values(payload, "cash_and_equivalents", roic_periods)
        vals, out_p = [], []
        for p, o, t, pt, d, e, c in zip(roic_periods, op_inc, tax, pretax, debt, eq, cash):
            tax_rate = (t / pt) if pt else 0.0
            tax_rate = min(max(tax_rate, 0.0), 1.0)
            nopat = o * (1 - tax_rate)
            invested_capital = d + e - c
            if invested_capital:
                out_p.append(p)
                vals.append(round(nopat / invested_capital * 100, 3))
        if out_p:
            facts.extend(util.period_facts(
                metric="roic", category=CATEGORY, periods=out_p, values=vals,
                unit="%",
                formula="NOPAT / Invested Capital * 100, where NOPAT = EBIT*(1 - effective tax rate), "
                        "Invested Capital = Total Debt + Equity - Cash",
            ))
        else:
            facts.append(unavailable(metric="roic", category=CATEGORY,
                                      reason="Invested capital is zero in all overlapping periods."))
    else:
        facts.append(unavailable(
            metric="roic", category=CATEGORY,
            reason="Requires 'operating_income', 'income_tax', 'pretax_income', 'total_debt', 'equity', 'cash_and_equivalents'.",
        ))

    return facts
