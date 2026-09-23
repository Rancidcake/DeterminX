"""Working Capital & Credit Intelligence Agent (sections 11-14 of the V2 brief).

Deterministic Tandon Method II style working-capital assessment:

    TCA = Total (Gross) Current Assets
    WCG = TCA - Current Liabilities
    Minimum stipulated NWC = 25% of TCA
    Estimated MPBF = WCG - Minimum stipulated NWC

MPBF is always reported ESTIMATED (never "precise" / bank-grade) because the
inputs needed for a real MPBF/Drawing Power computation — existing sanctioned
limits, inventory/receivables ageing, borrower contribution history, CMA data
— are not part of the ingested financial statements (section 13).
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from metrics import util
from metrics.schema import Fact, calculated, estimated, requires_document, unavailable
from src import db as _db

CATEGORY = "credit"
_MIN_NWC_PCT = 0.25  # 25% of TCA — the Tandon Method II stipulated minimum


def compute_working_capital_facts(payload: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []
    currency = str((payload.get("entity") or {}).get("currency") or "") or "currency"

    ca_cl_periods = util.common_periods(payload, ["current_assets", "current_liabilities"])
    if not ca_cl_periods:
        for m in ("gross_working_capital", "working_capital_gap", "minimum_stipulated_nwc",
                   "borrower_contribution", "estimated_mpbf", "current_asset_coverage_ratio"):
            facts.append(unavailable(metric=m, category=CATEGORY,
                                      reason="Requires 'current_assets' and 'current_liabilities'."))
    else:
        ca = util.aligned_values(payload, "current_assets", ca_cl_periods)
        cl = util.aligned_values(payload, "current_liabilities", ca_cl_periods)

        facts.extend(util.period_facts(
            metric="gross_working_capital", category=CATEGORY, periods=ca_cl_periods, values=ca,
            unit=currency, formula="Total Current Assets (TCA), as reported",
        ))

        wcg = [a - l for a, l in zip(ca, cl)]
        facts.extend(util.period_facts(
            metric="working_capital_gap", category=CATEGORY, periods=ca_cl_periods, values=wcg,
            unit=currency,
            formula="TCA - Current Liabilities (Tandon Method II) — 'current_liabilities' here includes "
                    "all current liabilities, not only bank borrowings, since the two are not distinguished "
                    "in the ingested statement",
            status="ESTIMATED",
        ))

        min_nwc = [round(a * _MIN_NWC_PCT, 2) for a in ca]
        facts.extend(util.period_facts(
            metric="minimum_stipulated_nwc", category=CATEGORY, periods=ca_cl_periods, values=min_nwc,
            unit=currency, formula=f"{_MIN_NWC_PCT:.0%} of TCA (Tandon Method II stipulated minimum)",
            status="ESTIMATED",
        ))

        borrower_contribution = [a - l for a, l in zip(ca, cl)]  # actual NWC maintained
        facts.extend(util.period_facts(
            metric="borrower_contribution", category=CATEGORY, periods=ca_cl_periods, values=borrower_contribution,
            unit=currency, formula="Actual Net Working Capital maintained (TCA - Current Liabilities)",
            status="ESTIMATED",
        ))

        estimated_mpbf = [round(g - m, 2) for g, m in zip(wcg, min_nwc)]
        facts.extend(util.period_facts(
            metric="estimated_mpbf", category=CATEGORY, periods=ca_cl_periods, values=estimated_mpbf,
            unit=currency,
            formula="ESTIMATED, NOT bank-grade: Working Capital Gap - Minimum Stipulated NWC "
                    "(Tandon Method II, second method of lending). Real MPBF/Drawing Power also requires "
                    "existing sanctioned limits, inventory/receivables ageing, borrower contribution history, "
                    "and CMA data, none of which are ingested here.",
            status="ESTIMATED",
        ))

        car = [round(a / l, 3) if l != 0 else None for a, l in zip(ca, cl)]
        facts.extend(util.period_facts(
            metric="current_asset_coverage_ratio", category=CATEGORY, periods=ca_cl_periods, values=car,
            unit="ratio", formula="Current Assets / Current Liabilities",
        ))

    facts.append(requires_document(
        metric="estimated_drawing_power", category=CATEGORY,
        reason=(
            "Drawing Power requires bank-specific inventory and receivables margin percentages from the "
            "sanction letter, plus current inventory/receivables ageing — none of which are part of the "
            "ingested financial statements. It is never estimated from the balance sheet alone."
        ),
        formula="(Paid Stock Value x (1 - inventory margin%)) + (Eligible Receivables x (1 - receivables margin%)) - Creditors",
    ))

    # ── Operating cycle / inventory holding period / DSO / DPO / CCC ───────
    dso_map = _days(payload, "accounts_receivable", "revenue", facts, "dso",
                     "average(Accounts Receivable) / Revenue * 365")
    dio_map = _days(payload, "inventory", "cost_of_revenue", facts, "inventory_holding_period",
                     "average(Inventory) / Cost of Revenue * 365")
    dpo_map = _days(payload, "accounts_payable", "cost_of_revenue", facts, "dpo",
                     "average(Accounts Payable) / Cost of Revenue * 365")

    oc_common = sorted(set(dso_map) & set(dio_map), key=util.period_sort_key)
    if oc_common:
        oc_vals = [round(dso_map[p] + dio_map[p], 2) for p in oc_common]
        facts.extend(util.period_facts(
            metric="operating_cycle", category=CATEGORY, periods=oc_common, values=oc_vals,
            unit="days", formula="DSO + Inventory Holding Period (DIO)",
        ))
    else:
        facts.append(unavailable(metric="operating_cycle", category=CATEGORY,
                                  reason="Requires DSO and Inventory Holding Period for overlapping periods."))

    ccc_common = sorted(set(dso_map) & set(dio_map) & set(dpo_map), key=util.period_sort_key)
    if ccc_common:
        ccc_vals = [round(dso_map[p] + dio_map[p] - dpo_map[p], 2) for p in ccc_common]
        facts.extend(util.period_facts(
            metric="cash_conversion_cycle", category=CATEGORY, periods=ccc_common, values=ccc_vals,
            unit="days", formula="DSO + DIO - DPO",
        ))
    else:
        facts.append(unavailable(metric="cash_conversion_cycle", category=CATEGORY,
                                  reason="Requires DSO, DIO, and DPO for overlapping periods."))

    return facts


def _days(payload, balance_field, flow_field, facts: list, metric_name, formula) -> dict[str, float]:
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
            v = round(abs(b) / abs(f) * 365.0, 2)
            out_p.append(p)
            vals.append(v)
            out_map[p] = v
    if out_p:
        facts.extend(util.period_facts(
            metric=metric_name, category=CATEGORY, periods=out_p, values=vals, unit="days", formula=formula,
        ))
    else:
        facts.append(unavailable(metric=metric_name, category=CATEGORY,
                                  reason=f"'{flow_field}' is zero in all overlapping periods."))
    return out_map


def run(
    *, entity: str, payload: dict[str, Any], dscr_facts: list[Fact] | None = None,
    base_url: str, model: str, api_key: str, run_id: str | None = None,
) -> dict[str, Any]:
    facts = compute_working_capital_facts(payload)
    facts_by_status: dict[str, list[dict[str, Any]]] = {}
    for f in facts:
        facts_by_status.setdefault(f.status, []).append(f.to_dict())

    llm_facts = [
        {"metric": f.metric, "value": f.value, "unit": f.unit, "period": f.period, "status": f.status}
        for f in facts if f.status in ("CALCULATED", "ESTIMATED")
    ]

    dscr_summary = None
    if dscr_facts:
        calc = [f for f in dscr_facts if f.metric == "dscr" and f.status == "CALCULATED"]
        if calc:
            latest = sorted(calc, key=lambda f: f.period or "")[-1]
            dscr_summary = {"period": latest.period, "value": latest.value}

    system = (
        "You are a credit analyst explaining a working-capital assessment. Use ONLY the provided facts — "
        "do not compute, estimate, or invent any new numbers. Explicitly note that any 'estimated_mpbf' or "
        "'estimated_drawing_power'-related figures are estimates, not bank-grade sanctioned limits. "
        "Do not provide a credit approval/rejection decision. Write 5-8 concise, professional sentences."
    )
    human = {
        "task": "Explain the company's working-capital position and estimated financing headroom.",
        "entity": entity,
        "facts": llm_facts,
        "dscr": dscr_summary,
        "unavailable_or_document_required": [
            {"metric": f.metric, "status": f.status, "reason": (f.warnings[0] if f.warnings else "")}
            for f in facts if f.status not in ("CALCULATED", "ESTIMATED")
        ],
    }

    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0)
    messages = [SystemMessage(content=system), HumanMessage(content=json.dumps(human, indent=2))]
    resp = _db.instrumented_invoke(
        llm, messages, run_id=run_id, agent_name="working_capital_agent", model=model, base_url=base_url,
    )
    narrative = (getattr(resp, "content", "") or "").strip() or "(No narrative generated.)"

    return {
        "entity": entity,
        "facts": [f.to_dict() for f in facts],
        "dscr": dscr_summary,
        "narrative": narrative,
    }
