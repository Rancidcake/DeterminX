"""2.3 Profitability Intelligence — gross/EBITDA/EBIT/operating/net margins, EPS."""

from __future__ import annotations

from typing import Any

from metrics import util
from metrics.schema import CATEGORY_PROFITABILITY, Fact, unavailable

CATEGORY = CATEGORY_PROFITABILITY


def _margin(payload, numerator_field, denom_field="revenue"):
    periods = util.common_periods(payload, [numerator_field, denom_field])
    if not periods:
        return periods, [], []
    num = util.aligned_values(payload, numerator_field, periods)
    den = util.aligned_values(payload, denom_field, periods)
    margin = [util.safe_div(n, d) for n, d in zip(num, den)]
    margin = [round(m * 100, 3) if m is not None else None for m in margin]
    return periods, num, margin


def compute(payload: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []
    currency = str((payload.get("entity") or {}).get("currency") or "") or "currency"

    # ── Gross Profit / Gross Margin ────────────────────────────────────────
    gp_periods = util.common_periods(payload, ["gross_profit"])
    gp_status = "CALCULATED"
    if gp_periods:
        gp_vals = util.aligned_values(payload, "gross_profit", gp_periods)
        gp_formula = "As reported"
    else:
        gp_periods = util.common_periods(payload, ["revenue", "cost_of_revenue"])
        gp_status = "ESTIMATED"
        gp_formula = "Revenue - Cost of Revenue (derived)"
        if gp_periods:
            rev = util.aligned_values(payload, "revenue", gp_periods)
            cogs = util.aligned_values(payload, "cost_of_revenue", gp_periods)
            gp_vals = [r - c for r, c in zip(rev, cogs)]
        else:
            gp_vals = []

    if gp_periods:
        facts.extend(util.period_facts(
            metric="gross_profit", category=CATEGORY, periods=gp_periods, values=gp_vals,
            unit=currency, formula=gp_formula, status=gp_status,
        ))
        rev_map = util.series_map(payload, "revenue")
        gm_periods, gm = [], []
        for p, v in zip(gp_periods, gp_vals):
            if p in rev_map and rev_map[p] != 0:
                gm_periods.append(p)
                gm.append(round(v / rev_map[p] * 100, 3))
        if gm_periods:
            facts.extend(util.period_facts(
                metric="gross_margin", category=CATEGORY, periods=gm_periods, values=gm,
                unit="%", formula="Gross Profit / Revenue * 100", status=gp_status,
            ))
        else:
            facts.append(unavailable(metric="gross_margin", category=CATEGORY,
                                      reason="Requires 'revenue' for the same period(s) as gross profit."))
    else:
        facts.append(unavailable(metric="gross_profit", category=CATEGORY,
                                  reason="Requires 'gross_profit', or 'revenue' and 'cost_of_revenue'."))
        facts.append(unavailable(metric="gross_margin", category=CATEGORY,
                                  reason="Requires 'gross_profit' and 'revenue' for the same period(s)."))

    # ── EBITDA / EBITDA margin ─────────────────────────────────────────────
    ebitda_periods = util.common_periods(payload, ["ebitda"])
    ebitda_status = "CALCULATED"
    if ebitda_periods:
        ebitda_vals = util.aligned_values(payload, "ebitda", ebitda_periods)
        ebitda_formula = "As reported"
    else:
        ebitda_periods = util.common_periods(payload, ["operating_income", "depreciation"])
        ebitda_status = "ESTIMATED"
        ebitda_formula = "Operating Income + Depreciation & Amortization (derived)"
        if ebitda_periods:
            op_inc = util.aligned_values(payload, "operating_income", ebitda_periods)
            dep = util.aligned_values(payload, "depreciation", ebitda_periods)
            ebitda_vals = [o + d for o, d in zip(op_inc, dep)]
        else:
            ebitda_vals = []

    if ebitda_periods:
        facts.extend(util.period_facts(
            metric="ebitda", category=CATEGORY, periods=ebitda_periods, values=ebitda_vals,
            unit=currency, formula=ebitda_formula, status=ebitda_status,
        ))
        rev_map = util.series_map(payload, "revenue")
        em_periods, em = [], []
        for p, v in zip(ebitda_periods, ebitda_vals):
            if p in rev_map and rev_map[p] != 0:
                em_periods.append(p)
                em.append(round(v / rev_map[p] * 100, 3))
        if em_periods:
            facts.extend(util.period_facts(
                metric="ebitda_margin", category=CATEGORY, periods=em_periods, values=em,
                unit="%", formula="EBITDA / Revenue * 100", status=ebitda_status,
            ))
        else:
            facts.append(unavailable(metric="ebitda_margin", category=CATEGORY,
                                      reason="Requires 'revenue' for the same period(s) as EBITDA."))
    else:
        facts.append(unavailable(metric="ebitda", category=CATEGORY,
                                  reason="Requires 'ebitda', or 'operating_income' and 'depreciation'."))
        facts.append(unavailable(metric="ebitda_margin", category=CATEGORY,
                                  reason="Requires 'ebitda' and 'revenue' for the same period(s)."))

    # ── EBIT / Operating Profit / Operating Margin ─────────────────────────
    ebit_periods = util.common_periods(payload, ["operating_income"])
    if ebit_periods:
        vals = util.aligned_values(payload, "operating_income", ebit_periods)
        facts.extend(util.period_facts(
            metric="ebit", category=CATEGORY, periods=ebit_periods, values=vals, unit=currency,
            formula="As reported (operating_income canonical field, treated as EBIT/Operating Profit)",
        ))
        facts.extend(util.period_facts(
            metric="operating_profit", category=CATEGORY, periods=ebit_periods, values=vals, unit=currency,
            formula="Same as EBIT (operating_income)",
        ))
    else:
        facts.append(unavailable(metric="ebit", category=CATEGORY, reason="Requires 'operating_income'."))
        facts.append(unavailable(metric="operating_profit", category=CATEGORY, reason="Requires 'operating_income'."))

    om_periods, _, om = _margin(payload, "operating_income")
    if om_periods:
        facts.extend(util.period_facts(
            metric="operating_margin", category=CATEGORY, periods=om_periods, values=om,
            unit="%", formula="Operating Income / Revenue * 100",
        ))
    else:
        facts.append(unavailable(metric="operating_margin", category=CATEGORY,
                                  reason="Requires 'operating_income' and 'revenue' for the same period(s)."))

    # ── PBT / PAT / Net Margin ─────────────────────────────────────────────
    for metric, field in (("pbt", "pretax_income"), ("pat", "net_income")):
        periods = util.common_periods(payload, [field])
        if periods:
            vals = util.aligned_values(payload, field, periods)
            facts.extend(util.period_facts(
                metric=metric, category=CATEGORY, periods=periods, values=vals, unit=currency,
                formula="As reported",
            ))
        else:
            facts.append(unavailable(metric=metric, category=CATEGORY, reason=f"Requires '{field}'."))

    nm_periods, _, nm = _margin(payload, "net_income")
    if nm_periods:
        facts.extend(util.period_facts(
            metric="net_profit_margin", category=CATEGORY, periods=nm_periods, values=nm,
            unit="%", formula="Net Income / Revenue * 100",
        ))
    else:
        facts.append(unavailable(metric="net_profit_margin", category=CATEGORY,
                                  reason="Requires 'net_income' and 'revenue' for the same period(s)."))

    # ── EPS / Diluted EPS ───────────────────────────────────────────────────
    for metric, field in (("eps", "basic_eps"), ("diluted_eps", "diluted_eps")):
        periods = util.common_periods(payload, [field])
        if periods:
            vals = util.aligned_values(payload, field, periods)
            facts.extend(util.period_facts(
                metric=metric, category=CATEGORY, periods=periods, values=vals,
                unit=currency + "/share", formula="As reported",
            ))
        else:
            facts.append(unavailable(metric=metric, category=CATEGORY, reason=f"Requires '{field}'."))

    return facts
