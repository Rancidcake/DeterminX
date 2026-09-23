"""2.6 Debt Servicing Intelligence — Interest Coverage, DSCR, Fixed Charge Coverage.

Per the V2 brief (section 2.6 / 14): DSCR must NEVER be fabricated. Precise
DSCR requires a debt repayment/maturity schedule (principal due per period),
which is not part of the standard ingested financial statement. This module
only computes DSCR when the caller supplies `payload["debt_schedule"]` —
an optional, explicitly user-provided mapping of period -> principal
repayment due. Absent that, DSCR is reported REQUIRES_ADDITIONAL_DOCUMENT,
never estimated or guessed.
"""

from __future__ import annotations

from typing import Any

from metrics import util
from metrics.schema import CATEGORY_DEBT_SERVICE, Fact, unavailable, requires_document

CATEGORY = CATEGORY_DEBT_SERVICE


def _debt_schedule(payload: dict[str, Any]) -> dict[str, float]:
    """Optional caller-supplied {period: principal_repayment_due}."""
    raw = payload.get("debt_schedule")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for p, v in raw.items():
        try:
            out[str(p)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def compute(payload: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []

    ic_periods = util.common_periods(payload, ["operating_income", "interest_expense"])
    if ic_periods:
        op_inc = util.aligned_values(payload, "operating_income", ic_periods)
        ie = util.aligned_values(payload, "interest_expense", ic_periods)
        ic = [round(o / i, 3) if i != 0 else None for o, i in zip(op_inc, ie)]
        facts.extend(util.period_facts(
            metric="interest_coverage_ratio", category=CATEGORY, periods=ic_periods, values=ic,
            unit="ratio", formula="Operating Income (EBIT) / Interest Expense",
        ))
    else:
        facts.append(unavailable(metric="interest_coverage_ratio", category=CATEGORY,
                                  reason="Requires 'operating_income' and 'interest_expense'."))

    fcc_periods = util.common_periods(payload, ["operating_income", "interest_expense", "depreciation"])
    if fcc_periods:
        op_inc = util.aligned_values(payload, "operating_income", fcc_periods)
        ie = util.aligned_values(payload, "interest_expense", fcc_periods)
        dep = util.aligned_values(payload, "depreciation", fcc_periods)
        fcc = []
        for o, i, d in zip(op_inc, ie, dep):
            fixed_charges = i  # lease/rent components are not ingested; interest is the only
            # deterministically available fixed charge.
            fcc.append(round((o + d) / fixed_charges, 3) if fixed_charges != 0 else None)
        facts.extend(util.period_facts(
            metric="fixed_charge_coverage", category=CATEGORY, periods=fcc_periods, values=fcc,
            unit="ratio",
            formula="(Operating Income + Depreciation) / Interest Expense — lease/rent obligations excluded (not ingested)",
            status="ESTIMATED",
        ))
    else:
        facts.append(unavailable(metric="fixed_charge_coverage", category=CATEGORY,
                                  reason="Requires 'operating_income', 'interest_expense', and 'depreciation'."))

    schedule = _debt_schedule(payload)
    if not schedule:
        facts.append(requires_document(
            metric="dscr", category=CATEGORY,
            reason=(
                "Precise DSCR requires a debt repayment/maturity schedule (principal due per "
                "period), which was not supplied. Provide one via the debt schedule input to "
                "enable this calculation — it will not be estimated from the income statement alone."
            ),
            formula="(PAT + Depreciation + Interest) / (Principal Repayment + Interest)",
        ))
        return facts

    dscr_periods = util.common_periods(payload, ["net_income", "depreciation", "interest_expense"])
    dscr_periods = [p for p in dscr_periods if p in schedule]
    if not dscr_periods:
        facts.append(requires_document(
            metric="dscr", category=CATEGORY,
            reason="Debt schedule supplied but has no periods overlapping with net_income/depreciation/interest_expense.",
            formula="(PAT + Depreciation + Interest) / (Principal Repayment + Interest)",
        ))
        return facts

    ni = util.aligned_values(payload, "net_income", dscr_periods)
    dep = util.aligned_values(payload, "depreciation", dscr_periods)
    ie = util.aligned_values(payload, "interest_expense", dscr_periods)
    dscr_vals = []
    for p, n, d, i in zip(dscr_periods, ni, dep, ie):
        principal = schedule[p]
        denom = principal + i
        dscr_vals.append(round((n + d + i) / denom, 3) if denom != 0 else None)

    facts.extend(util.period_facts(
        metric="dscr", category=CATEGORY, periods=dscr_periods, values=dscr_vals,
        unit="ratio",
        formula="(PAT + Depreciation + Interest) / (Principal Repayment + Interest), using the supplied debt schedule",
    ))

    return facts
