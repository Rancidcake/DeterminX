"""Domain-Specific (sector) Intelligence — SaaS / Banking / Retail / Manufacturing.

Standard financial statements are sector-agnostic (revenue, assets, equity —
the same shape for a software company and a steel mill). Real investors judge
each sector against metrics that mostly live OUTSIDE the financial statements
— customer counts, churn, interest income breakdowns, store footprint,
installed capacity. This module follows the exact same rule as everything
else: compute in Python from whatever IS available, and report the rest as
REQUIRES_ADDITIONAL_DOCUMENT with the precise operational input that would
unlock it — never fabricate a customer count or a churn rate.

Activation is opt-in and additive: `payload.get("sector")` defaults to
"general", which produces zero domain facts (zero behaviour change for every
existing user of the engine). Optional `payload.get("domain_inputs", {})`
carries the operational figures a financial statement never contains (e.g.
`{"sales_marketing_expense": 5e8, "new_customers": 1200, "churn_rate_pct": 3.5}`).

A few metrics — notably SaaS's "Rule of 40" — ARE fully derivable from the
existing Fact categories (revenue growth + margin), so those are computed
even with zero domain_inputs supplied, by re-using `growth.compute()` and
`profitability.compute()` rather than re-deriving the numbers.
"""

from __future__ import annotations

from typing import Any

from metrics import growth, profitability, util
from metrics.schema import CATEGORY_DOMAIN, Fact, requires_document, unavailable

CATEGORY = CATEGORY_DOMAIN
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def _inputs(payload: dict[str, Any]) -> dict[str, float]:
    raw = payload.get("domain_inputs")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _need(inp: dict[str, float], *keys: str) -> bool:
    return all(k in inp and inp[k] not in (None,) for k in keys)


# ---------------------------------------------------------------------------
# SaaS / Software
# ---------------------------------------------------------------------------

def _compute_saas(payload: dict[str, Any], inp: dict[str, float]) -> list[Fact]:
    facts: list[Fact] = []
    currency = str((payload.get("entity") or {}).get("currency") or "") or "currency"

    # Rule of 40 = Revenue Growth % + Profit Margin % — fully derivable from
    # facts other categories already computed, no domain_inputs required.
    growth_facts = growth.compute(payload)
    profit_facts = profitability.compute(payload)
    rev_growth = (util.latest_from_facts(growth_facts, "revenue_cagr")
                  or util.latest_from_facts(growth_facts, "revenue_growth"))
    margin = (util.latest_from_facts(profit_facts, "ebitda_margin")
              or util.latest_from_facts(profit_facts, "net_profit_margin"))
    if rev_growth is not None and margin is not None:
        score = round(rev_growth.value + margin.value, 2)
        status = "ESTIMATED" if "ESTIMATED" in (rev_growth.status, margin.status) else "CALCULATED"
        facts.append(util.summary_fact(
            metric="rule_of_40", category=CATEGORY, value=score, unit="score", status=status,
            formula=f"Revenue Growth ({rev_growth.metric} = {rev_growth.value}%) + "
                    f"Profit Margin ({margin.metric} = {margin.value}%)",
        ))
        r40_status = PASS if score >= 40 else (WARN if score >= 30 else FAIL)
        facts.append(util.summary_fact(
            metric="rule_of_40_status", category=CATEGORY, value=r40_status, unit="status", status=status,
            formula="PASS if Rule of 40 score >= 40; WARN if >= 30; else FAIL",
        ))
    else:
        facts.append(unavailable(metric="rule_of_40", category=CATEGORY,
                                  reason="Requires a computable revenue growth rate and margin (EBITDA or net)."))
        facts.append(unavailable(metric="rule_of_40_status", category=CATEGORY,
                                  reason="Requires 'rule_of_40'."))

    # R&D intensity — computable when rd_expense is ingested (no domain_inputs needed).
    rd_periods = util.common_periods(payload, ["rd_expense", "revenue"])
    if rd_periods:
        rd = util.aligned_values(payload, "rd_expense", rd_periods)
        rev = util.aligned_values(payload, "revenue", rd_periods)
        vals = [round(r / v * 100, 3) if v else None for r, v in zip(rd, rev)]
        facts.extend(util.period_facts(
            metric="rd_intensity", category=CATEGORY, periods=rd_periods, values=vals,
            unit="%", formula="R&D Expense / Revenue * 100",
        ))
    else:
        facts.append(unavailable(metric="rd_intensity", category=CATEGORY,
                                  reason="Requires 'rd_expense' and 'revenue'."))

    # Everything below needs customer/subscription data no financial statement carries.
    if _need(inp, "sales_marketing_expense", "new_customers") and inp["new_customers"] > 0:
        cac = round(inp["sales_marketing_expense"] / inp["new_customers"], 2)
        facts.append(util.summary_fact(
            metric="cac", category=CATEGORY, value=cac, unit=f"{currency}/customer",
            formula="Sales & Marketing Expense / New Customers Acquired (from domain_inputs)",
        ))
    else:
        facts.append(requires_document(
            metric="cac", category=CATEGORY,
            reason="Requires domain_inputs 'sales_marketing_expense' and 'new_customers' — "
                   "not present in a standard financial statement.",
            formula="Sales & Marketing Expense / New Customers Acquired",
        ))
        cac = None

    arpu = None
    if _need(inp, "recurring_revenue", "total_customers") and inp["total_customers"] > 0:
        arpu = inp["recurring_revenue"] / inp["total_customers"]
        facts.append(util.summary_fact(
            metric="arpu", category=CATEGORY, value=round(arpu, 2), unit=f"{currency}/customer",
            formula="Recurring Revenue / Total Customers (from domain_inputs)",
        ))
    else:
        facts.append(requires_document(
            metric="arpu", category=CATEGORY,
            reason="Requires domain_inputs 'recurring_revenue' and 'total_customers'.",
            formula="Recurring Revenue / Total Customers",
        ))

    gross_margin_fact = util.latest_from_facts(profit_facts, "gross_margin")
    gm_frac = (gross_margin_fact.value / 100.0) if gross_margin_fact else None

    if arpu is not None and gm_frac is not None and _need(inp, "churn_rate_pct") and inp["churn_rate_pct"] > 0:
        ltv = round(arpu * gm_frac / (inp["churn_rate_pct"] / 100.0), 2)
        facts.append(util.summary_fact(
            metric="ltv", category=CATEGORY, value=ltv, unit=f"{currency}/customer",
            formula="(ARPU * Gross Margin %) / Churn Rate % (uses domain_inputs 'churn_rate_pct')",
        ))
        if cac and cac > 0:
            facts.append(util.summary_fact(
                metric="ltv_to_cac_ratio", category=CATEGORY, value=round(ltv / cac, 2), unit="ratio",
                formula="LTV / CAC",
            ))
        else:
            facts.append(requires_document(metric="ltv_to_cac_ratio", category=CATEGORY,
                                             reason="Requires 'cac' (see above).", formula="LTV / CAC"))
        if cac and gm_frac:
            monthly_gross_profit_per_customer = arpu * gm_frac / 12.0
            if monthly_gross_profit_per_customer:
                facts.append(util.summary_fact(
                    metric="cac_payback_months", category=CATEGORY,
                    value=round(cac / monthly_gross_profit_per_customer, 2), unit="months",
                    formula="CAC / (ARPU * Gross Margin % / 12)",
                ))
    else:
        facts.append(requires_document(
            metric="ltv", category=CATEGORY,
            reason="Requires 'arpu' (see above), a computable gross margin, and domain_inputs 'churn_rate_pct'.",
            formula="(ARPU * Gross Margin %) / Churn Rate %",
        ))
        facts.append(requires_document(metric="ltv_to_cac_ratio", category=CATEGORY,
                                        reason="Requires 'ltv' and 'cac'.", formula="LTV / CAC"))
        facts.append(requires_document(metric="cac_payback_months", category=CATEGORY,
                                        reason="Requires 'cac' and 'ltv' inputs.",
                                        formula="CAC / (ARPU * Gross Margin % / 12)"))

    if _need(inp, "beginning_arr", "expansion_revenue", "churned_revenue") and inp["beginning_arr"] > 0:
        nrr = round((inp["beginning_arr"] + inp["expansion_revenue"] - inp["churned_revenue"])
                    / inp["beginning_arr"] * 100, 2)
        facts.append(util.summary_fact(
            metric="net_revenue_retention", category=CATEGORY, value=nrr, unit="%",
            formula="(Beginning ARR + Expansion Revenue - Churned Revenue) / Beginning ARR * 100",
        ))
    else:
        facts.append(requires_document(
            metric="net_revenue_retention", category=CATEGORY,
            reason="Requires domain_inputs 'beginning_arr', 'expansion_revenue', 'churned_revenue'.",
            formula="(Beginning ARR + Expansion Revenue - Churned Revenue) / Beginning ARR * 100",
        ))

    return facts


# ---------------------------------------------------------------------------
# Banking / NBFC
# ---------------------------------------------------------------------------

def _compute_banking(payload: dict[str, Any], inp: dict[str, float]) -> list[Fact]:
    facts: list[Fact] = []

    if _need(inp, "interest_income", "interest_expense_on_funds", "avg_earning_assets") and inp["avg_earning_assets"] > 0:
        nim = round((inp["interest_income"] - inp["interest_expense_on_funds"]) / inp["avg_earning_assets"] * 100, 3)
        facts.append(util.summary_fact(
            metric="net_interest_margin", category=CATEGORY, value=nim, unit="%",
            formula="(Interest Income - Interest Expense on Funds) / Average Earning Assets * 100 "
                    "(from domain_inputs — not derivable from a standard non-bank statement schema)",
        ))
    else:
        facts.append(requires_document(
            metric="net_interest_margin", category=CATEGORY,
            reason="Requires domain_inputs 'interest_income', 'interest_expense_on_funds', 'avg_earning_assets'.",
            formula="(Interest Income - Interest Expense on Funds) / Average Earning Assets * 100",
        ))

    if _need(inp, "gross_npa", "gross_advances") and inp["gross_advances"] > 0:
        facts.append(util.summary_fact(
            metric="gross_npa_ratio", category=CATEGORY,
            value=round(inp["gross_npa"] / inp["gross_advances"] * 100, 3), unit="%",
            formula="Gross NPA / Gross Advances * 100 (from domain_inputs)",
        ))
    else:
        facts.append(requires_document(metric="gross_npa_ratio", category=CATEGORY,
                                        reason="Requires domain_inputs 'gross_npa' and 'gross_advances'.",
                                        formula="Gross NPA / Gross Advances * 100"))

    if _need(inp, "casa_deposits", "total_deposits") and inp["total_deposits"] > 0:
        facts.append(util.summary_fact(
            metric="casa_ratio", category=CATEGORY,
            value=round(inp["casa_deposits"] / inp["total_deposits"] * 100, 3), unit="%",
            formula="CASA Deposits / Total Deposits * 100 (from domain_inputs)",
        ))
    else:
        facts.append(requires_document(metric="casa_ratio", category=CATEGORY,
                                        reason="Requires domain_inputs 'casa_deposits' and 'total_deposits'.",
                                        formula="CASA Deposits / Total Deposits * 100"))

    if _need(inp, "capital_adequacy_ratio_pct"):
        facts.append(util.summary_fact(
            metric="capital_adequacy_ratio", category=CATEGORY,
            value=round(inp["capital_adequacy_ratio_pct"], 3), unit="%",
            formula="As disclosed (regulatory figure, from domain_inputs — not derivable)",
        ))
    else:
        facts.append(requires_document(
            metric="capital_adequacy_ratio", category=CATEGORY,
            reason="A regulatory disclosure, not derivable from financial statements — "
                   "provide domain_inputs 'capital_adequacy_ratio_pct'.",
        ))

    return facts


# ---------------------------------------------------------------------------
# Retail / E-commerce
# ---------------------------------------------------------------------------

def _compute_retail(payload: dict[str, Any], inp: dict[str, float]) -> list[Fact]:
    facts: list[Fact] = []
    latest_revenue = util.latest_of(payload, "revenue")

    if _need(inp, "same_store_revenue_current", "same_store_revenue_prior") and inp["same_store_revenue_prior"] > 0:
        sss = round((inp["same_store_revenue_current"] - inp["same_store_revenue_prior"])
                    / inp["same_store_revenue_prior"] * 100, 3)
        facts.append(util.summary_fact(
            metric="same_store_sales_growth", category=CATEGORY, value=sss, unit="%",
            formula="(Same-Store Revenue Current - Prior) / Prior * 100 (from domain_inputs)",
        ))
    else:
        facts.append(requires_document(
            metric="same_store_sales_growth", category=CATEGORY,
            reason="Requires domain_inputs 'same_store_revenue_current' and 'same_store_revenue_prior' "
                   "— store-level disclosure not in a standard financial statement.",
        ))

    if latest_revenue and _need(inp, "total_orders") and inp["total_orders"] > 0:
        _, rev_val = latest_revenue
        facts.append(util.summary_fact(
            metric="average_order_value", category=CATEGORY, value=round(rev_val / inp["total_orders"], 2),
            unit="currency/order", formula="Latest-period Revenue / Total Orders (from domain_inputs)",
        ))
    else:
        facts.append(requires_document(metric="average_order_value", category=CATEGORY,
                                        reason="Requires 'revenue' and domain_inputs 'total_orders'."))

    if latest_revenue and _need(inp, "retail_area_sqft") and inp["retail_area_sqft"] > 0:
        _, rev_val = latest_revenue
        facts.append(util.summary_fact(
            metric="sales_per_sqft", category=CATEGORY, value=round(rev_val / inp["retail_area_sqft"], 2),
            unit="currency/sqft", formula="Latest-period Revenue / Retail Area sqft (from domain_inputs)",
        ))
    else:
        facts.append(requires_document(metric="sales_per_sqft", category=CATEGORY,
                                        reason="Requires 'revenue' and domain_inputs 'retail_area_sqft'."))

    return facts


# ---------------------------------------------------------------------------
# Manufacturing
# ---------------------------------------------------------------------------

def _compute_manufacturing(payload: dict[str, Any], inp: dict[str, float]) -> list[Fact]:
    facts: list[Fact] = []

    if _need(inp, "installed_capacity_units", "actual_output_units") and inp["installed_capacity_units"] > 0:
        util_pct = round(inp["actual_output_units"] / inp["installed_capacity_units"] * 100, 3)
        facts.append(util.summary_fact(
            metric="capacity_utilization", category=CATEGORY, value=util_pct, unit="%",
            formula="Actual Output / Installed Capacity * 100 (from domain_inputs)",
        ))
    else:
        facts.append(requires_document(
            metric="capacity_utilization", category=CATEGORY,
            reason="Requires domain_inputs 'installed_capacity_units' and 'actual_output_units' "
                   "— plant capacity disclosure not in a standard financial statement.",
        ))

    latest_revenue = util.latest_of(payload, "revenue")
    if latest_revenue and _need(inp, "order_book_value") :
        _, rev_val = latest_revenue
        facts.append(util.summary_fact(
            metric="order_book_to_revenue", category=CATEGORY,
            value=round(inp["order_book_value"] / rev_val, 3) if rev_val else None, unit="ratio",
            formula="Order Book Value / Latest-period Revenue (from domain_inputs)",
        ))
    else:
        facts.append(requires_document(metric="order_book_to_revenue", category=CATEGORY,
                                        reason="Requires 'revenue' and domain_inputs 'order_book_value'."))

    return facts


_SECTOR_COMPUTE = {
    "saas": _compute_saas,
    "banking": _compute_banking,
    "retail": _compute_retail,
    "manufacturing": _compute_manufacturing,
}


def compute(payload: dict[str, Any]) -> list[Fact]:
    sector = str(payload.get("sector") or "general").strip().lower()
    if sector in ("general", "", "none"):
        return []

    fn = _SECTOR_COMPUTE.get(sector)
    if fn is None:
        return [unavailable(
            metric="sector_metrics", category=CATEGORY,
            reason=f"Unknown sector '{sector}'. Supported: {', '.join(_SECTOR_COMPUTE)}.",
        )]

    inp = _inputs(payload)
    return fn(payload, inp)
