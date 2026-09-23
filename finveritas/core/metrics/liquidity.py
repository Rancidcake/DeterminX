"""2.4 Liquidity Intelligence — current/quick/cash ratio, working capital."""

from __future__ import annotations

from typing import Any

from metrics import util
from metrics.schema import CATEGORY_LIQUIDITY, Fact, unavailable

CATEGORY = CATEGORY_LIQUIDITY


def compute(payload: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []
    currency = str((payload.get("entity") or {}).get("currency") or "") or "currency"

    ca_cl_periods = util.common_periods(payload, ["current_assets", "current_liabilities"])
    if ca_cl_periods:
        ca = util.aligned_values(payload, "current_assets", ca_cl_periods)
        cl = util.aligned_values(payload, "current_liabilities", ca_cl_periods)

        current_ratio = [round(util.safe_div(a, l), 3) if util.safe_div(a, l) is not None else None
                          for a, l in zip(ca, cl)]
        facts.extend(util.period_facts(
            metric="current_ratio", category=CATEGORY, periods=ca_cl_periods, values=current_ratio,
            unit="ratio", formula="Current Assets / Current Liabilities",
        ))

        working_capital = [a - l for a, l in zip(ca, cl)]
        facts.extend(util.period_facts(
            metric="working_capital", category=CATEGORY, periods=ca_cl_periods, values=working_capital,
            unit=currency, formula="Current Assets - Current Liabilities",
        ))
        facts.extend(util.period_facts(
            metric="net_working_capital", category=CATEGORY, periods=ca_cl_periods, values=working_capital,
            unit=currency, formula="Current Assets - Current Liabilities",
        ))

        inv_map = util.series_map(payload, "inventory")
        if inv_map:
            quick_periods, quick_vals = [], []
            for i, p in enumerate(ca_cl_periods):
                if p in inv_map and cl[i] != 0:
                    quick_periods.append(p)
                    quick_vals.append(round((ca[i] - inv_map[p]) / cl[i], 3))
            if quick_periods:
                facts.extend(util.period_facts(
                    metric="quick_ratio", category=CATEGORY, periods=quick_periods, values=quick_vals,
                    unit="ratio", formula="(Current Assets - Inventory) / Current Liabilities",
                ))
            else:
                facts.append(unavailable(metric="quick_ratio", category=CATEGORY,
                                          reason="No overlapping periods between inventory and current assets/liabilities."))
        else:
            facts.append(unavailable(
                metric="quick_ratio", category=CATEGORY,
                reason="Requires 'inventory'; not present in ingested data.",
            ))
    else:
        for m in ("current_ratio", "working_capital", "net_working_capital", "quick_ratio"):
            facts.append(unavailable(metric=m, category=CATEGORY,
                                      reason="Requires 'current_assets' and 'current_liabilities'."))

    cash_periods = util.common_periods(payload, ["cash_and_equivalents", "current_liabilities"])
    if cash_periods:
        cash = util.aligned_values(payload, "cash_and_equivalents", cash_periods)
        cl2 = util.aligned_values(payload, "current_liabilities", cash_periods)
        cash_ratio = [round(util.safe_div(c, l), 3) if util.safe_div(c, l) is not None else None
                      for c, l in zip(cash, cl2)]
        facts.extend(util.period_facts(
            metric="cash_ratio", category=CATEGORY, periods=cash_periods, values=cash_ratio,
            unit="ratio", formula="Cash & Equivalents / Current Liabilities",
        ))
    else:
        facts.append(unavailable(metric="cash_ratio", category=CATEGORY,
                                  reason="Requires 'cash_and_equivalents' and 'current_liabilities'."))

    return facts
