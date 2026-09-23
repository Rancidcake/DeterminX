"""2.7 Efficiency Intelligence — turnover ratios, cash conversion cycle, DSO/DIO/DPO."""

from __future__ import annotations

from typing import Any

from metrics import util
from metrics.schema import CATEGORY_EFFICIENCY, Fact, unavailable

CATEGORY = CATEGORY_EFFICIENCY
DAYS_IN_YEAR = 365.0


def _avg_balance(a: float, b: float | None) -> float:
    """Average of opening/closing balance when a prior period exists, else the single value."""
    return (a + b) / 2.0 if b is not None else a


def _turnover(payload, flow_field, balance_field, metric_name, formula_note):
    periods = util.common_periods(payload, [flow_field, balance_field])
    if not periods:
        return unavailable(metric=metric_name, category=CATEGORY,
                            reason=f"Requires '{flow_field}' and '{balance_field}'.")
    flow = util.aligned_values(payload, flow_field, periods)
    bal_map = util.series_map(payload, balance_field)
    vals, out_periods = [], []
    for i, p in enumerate(periods):
        prior = None
        idx = util.all_periods(payload)
        try:
            pos = idx.index(p)
            if pos > 0:
                prior = bal_map.get(idx[pos - 1])
        except ValueError:
            pass
        avg_bal = _avg_balance(bal_map[p], prior)
        if avg_bal:
            out_periods.append(p)
            vals.append(round(flow[i] / avg_bal, 3))
    if not out_periods:
        return unavailable(metric=metric_name, category=CATEGORY, reason="Balance value is zero in all overlapping periods.")
    facts = util.period_facts(metric=metric_name, category=CATEGORY, periods=out_periods, values=vals,
                               unit="turns/year", formula=formula_note)
    return facts


def compute(payload: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []

    r = _turnover(payload, "revenue", "total_assets", "asset_turnover",
                  "Revenue / average(Total Assets)")
    facts.extend(r if isinstance(r, list) else [r])

    r = _turnover(payload, "revenue", "accounts_receivable", "receivable_turnover",
                  "Revenue / average(Accounts Receivable)")
    facts.extend(r if isinstance(r, list) else [r])

    r = _turnover(payload, "cost_of_revenue", "accounts_payable", "payable_turnover",
                  "Cost of Revenue / average(Accounts Payable)")
    facts.extend(r if isinstance(r, list) else [r])

    r = _turnover(payload, "cost_of_revenue", "inventory", "inventory_turnover",
                  "Cost of Revenue / average(Inventory)")
    facts.extend(r if isinstance(r, list) else [r])

    wc_periods = util.common_periods(payload, ["revenue", "current_assets", "current_liabilities"])
    if wc_periods:
        rev = util.aligned_values(payload, "revenue", wc_periods)
        ca = util.aligned_values(payload, "current_assets", wc_periods)
        cl = util.aligned_values(payload, "current_liabilities", wc_periods)
        vals, out_p = [], []
        for p, r_, a, l in zip(wc_periods, rev, ca, cl):
            wc = a - l
            if wc:
                out_p.append(p)
                vals.append(round(r_ / wc, 3))
        if out_p:
            facts.extend(util.period_facts(
                metric="working_capital_turnover", category=CATEGORY, periods=out_p, values=vals,
                unit="turns/year", formula="Revenue / Working Capital",
            ))
        else:
            facts.append(unavailable(metric="working_capital_turnover", category=CATEGORY,
                                      reason="Working capital is zero in all overlapping periods."))
    else:
        facts.append(unavailable(metric="working_capital_turnover", category=CATEGORY,
                                  reason="Requires 'revenue', 'current_assets', 'current_liabilities'."))

    r = _turnover(payload, "revenue", "non_current_assets", "fixed_asset_turnover",
                  "Revenue / average(Non-Current / Fixed Assets)")
    facts.extend(r if isinstance(r, list) else [r])

    # ── DSO / DIO / DPO / Cash Conversion Cycle ─────────────────────────────
    dso_map = _days_metric(payload, "accounts_receivable", "revenue", facts, "dso",
                            "average(Accounts Receivable) / Revenue * 365")
    dio_map = _days_metric(payload, "inventory", "cost_of_revenue", facts, "dio",
                            "average(Inventory) / Cost of Revenue * 365")
    dpo_map = _days_metric(payload, "accounts_payable", "cost_of_revenue", facts, "dpo",
                            "average(Accounts Payable) / Cost of Revenue * 365")

    common = sorted(set(dso_map) & set(dio_map) & set(dpo_map), key=util.period_sort_key)
    if common:
        ccc_vals = [round(dso_map[p] + dio_map[p] - dpo_map[p], 2) for p in common]
        facts.extend(util.period_facts(
            metric="cash_conversion_cycle", category=CATEGORY, periods=common, values=ccc_vals,
            unit="days", formula="DSO + DIO - DPO",
        ))
    else:
        facts.append(unavailable(metric="cash_conversion_cycle", category=CATEGORY,
                                  reason="Requires DSO, DIO, and DPO for overlapping periods."))

    return facts


def _days_metric(payload, balance_field, flow_field, facts: list, metric_name, formula) -> dict[str, float]:
    periods = util.common_periods(payload, [balance_field, flow_field])
    if not periods:
        facts.append(unavailable(metric=metric_name, category=CATEGORY,
                                  reason=f"Requires '{balance_field}' and '{flow_field}'."))
        return {}
    bal = util.aligned_values(payload, balance_field, periods)
    flow = util.aligned_values(payload, flow_field, periods)
    out_p, vals, out_map = [], [], {}
    for p, b, f in zip(periods, bal, flow):
        if f != 0:
            v = round(abs(b) / abs(f) * DAYS_IN_YEAR, 2)
            out_p.append(p)
            vals.append(v)
            out_map[p] = v
    if out_p:
        facts.extend(util.period_facts(
            metric=metric_name, category=CATEGORY, periods=out_p, values=vals,
            unit="days", formula=formula,
        ))
    else:
        facts.append(unavailable(metric=metric_name, category=CATEGORY,
                                  reason=f"'{flow_field}' is zero in all overlapping periods."))
    return out_map
