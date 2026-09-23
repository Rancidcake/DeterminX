"""2.9 Cash Flow Intelligence — OCF, ICF, FCF, Free Cash Flow, CAPEX, cash burn."""

from __future__ import annotations

from typing import Any

from metrics import util
from metrics.schema import CATEGORY_CASH_FLOW, Fact, unavailable

CATEGORY = CATEGORY_CASH_FLOW

_DIRECT_FIELDS = {
    "operating_cash_flow": "operating_cash_flow",
    "investing_cash_flow": "investing_cash_flow",
    "financing_cash_flow": "financing_cash_flow",
    "capex": "capex",
}


def compute(payload: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []
    currency = str((payload.get("entity") or {}).get("currency") or "") or "currency"

    for metric, field in _DIRECT_FIELDS.items():
        periods = util.common_periods(payload, [field])
        if periods:
            vals = util.aligned_values(payload, field, periods)
            facts.extend(util.period_facts(
                metric=metric, category=CATEGORY, periods=periods, values=vals,
                unit=currency, formula="As reported (cash flow statement)",
            ))
        else:
            facts.append(unavailable(
                metric=metric, category=CATEGORY,
                reason=f"Requires '{field}' from a cash flow statement; not present in ingested data.",
            ))

    fcf_periods = util.common_periods(payload, ["operating_cash_flow", "capex"])
    if fcf_periods:
        ocf = util.aligned_values(payload, "operating_cash_flow", fcf_periods)
        capex = util.aligned_values(payload, "capex", fcf_periods)
        fcf = [o - abs(c) for o, c in zip(ocf, capex)]
        facts.extend(util.period_facts(
            metric="free_cash_flow", category=CATEGORY, periods=fcf_periods, values=fcf,
            unit=currency, formula="Operating Cash Flow - |CAPEX|",
        ))
    else:
        facts.append(unavailable(metric="free_cash_flow", category=CATEGORY,
                                  reason="Requires 'operating_cash_flow' and 'capex'."))

    ocfr_periods = util.common_periods(payload, ["operating_cash_flow", "current_liabilities"])
    if ocfr_periods:
        ocf = util.aligned_values(payload, "operating_cash_flow", ocfr_periods)
        cl = util.aligned_values(payload, "current_liabilities", ocfr_periods)
        vals = [round(o / l, 3) if l != 0 else None for o, l in zip(ocf, cl)]
        facts.extend(util.period_facts(
            metric="operating_cash_flow_ratio", category=CATEGORY, periods=ocfr_periods, values=vals,
            unit="ratio", formula="Operating Cash Flow / Current Liabilities",
        ))
    else:
        facts.append(unavailable(metric="operating_cash_flow_ratio", category=CATEGORY,
                                  reason="Requires 'operating_cash_flow' and 'current_liabilities'."))

    burn_periods = util.common_periods(payload, ["operating_cash_flow"])
    if burn_periods:
        ocf = util.aligned_values(payload, "operating_cash_flow", burn_periods)
        burn_p, burn_v = [], []
        for p, v in zip(burn_periods, ocf):
            if v < 0:
                burn_p.append(p)
                burn_v.append(round(abs(v), 2))
        if burn_p:
            facts.extend(util.period_facts(
                metric="cash_burn", category=CATEGORY, periods=burn_p, values=burn_v,
                unit=currency, formula="|Operating Cash Flow| in periods where Operating Cash Flow is negative",
            ))
        else:
            facts.append(util.summary_fact(
                metric="cash_burn", category=CATEGORY, value=0.0, unit=currency,
                formula="No period had negative operating cash flow.",
            ))
    else:
        facts.append(unavailable(metric="cash_burn", category=CATEGORY,
                                  reason="Requires 'operating_cash_flow'."))

    return facts
