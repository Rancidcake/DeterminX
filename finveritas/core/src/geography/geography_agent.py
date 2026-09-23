"""Geography-wise Impact Analysis Agent (sections 15-16 of the V2 brief).

    Regional revenue (user-entered / best-effort extracted)
        -> Python: revenue, share, YoY growth, volatility
        -> News/event matching for regions with a notable swing
        -> LLM narrates a POSSIBLE cause, clearly separated from the FACT

Regional revenue, share, growth, and volatility are always Python-computed.
The LLM is only ever shown those numbers plus optional headlines — it cannot
introduce a different revenue figure, and its causal commentary must be
framed as a hypothesis, not an established fact (enforced in the prompt and
by keeping "fact" and "possible_explanation" as separate output fields).
"""

from __future__ import annotations

import json
import statistics
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from metrics.util import period_sort_key
from src import db as _db
from src.external.news_provider import NewsProvider, company_search_name

_NOTABLE_SWING_PCT = 15.0


def compute_regional_metrics(
    regional_revenue: dict[str, dict[str, float]],
    total_revenue: dict[str, float],
) -> dict[str, Any]:
    """Pure Python: revenue / share / YoY growth / volatility per region.

    `regional_revenue`: {region: {period: value}}
    `total_revenue`: {period: value} — the company-wide revenue fact, used
    only to compute each region's share of total (never re-derived by the LLM).
    """
    regions: dict[str, Any] = {}
    for region, series in regional_revenue.items():
        periods = sorted(series.keys(), key=period_sort_key)
        if not periods:
            continue
        values = [series[p] for p in periods]

        shares = []
        for p, v in zip(periods, values):
            tot = total_revenue.get(p)
            shares.append(round(v / tot * 100, 2) if tot else None)

        growth = [None]
        for i in range(1, len(values)):
            prev = values[i - 1]
            growth.append(round((values[i] - prev) / abs(prev) * 100, 2) if prev else None)

        growth_clean = [g for g in growth if g is not None]
        volatility = round(statistics.pstdev(growth_clean), 3) if len(growth_clean) >= 2 else None

        latest_growth = growth[-1] if growth else None
        notable = isinstance(latest_growth, (int, float)) and abs(latest_growth) >= _NOTABLE_SWING_PCT

        regions[region] = {
            "periods": periods,
            "revenue": values,
            "revenue_share_pct": shares,
            "yoy_growth_pct": growth,
            "volatility": volatility,
            "latest_yoy_growth_pct": latest_growth,
            "notable_swing": notable,
        }

    return regions


def run(
    *,
    entity: str,
    regional_revenue: dict[str, dict[str, float]],
    total_revenue: dict[str, float],
    news_api_key: str = "",
    base_url: str, model: str, api_key: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    if not regional_revenue:
        return {
            "entity": entity, "status": "UNAVAILABLE",
            "reason": "No regional revenue data was entered. Geography analysis requires the regional "
                      "breakdown disclosed in the company's segment-reporting footnote (not typically "
                      "present in a Bloomberg statement export) — enter it manually to enable this agent.",
        }

    region_metrics = compute_regional_metrics(regional_revenue, total_revenue)
    notable_regions = [r for r, m in region_metrics.items() if m["notable_swing"]]

    news_provider = NewsProvider()
    news_by_region: dict[str, Any] = {}
    for region in notable_regions:
        result = news_provider.fetch(query=f"{company_search_name(entity)} {region}", api_key=news_api_key, max_articles=5)
        news_by_region[region] = result.to_dict()

    system = (
        "You are a financial analyst explaining regional revenue performance. "
        "All revenue, share, growth, and volatility figures were computed in Python and are FACTS — "
        "do not alter them or introduce new numbers. "
        "For any region with a notable swing, you may offer a POSSIBLE explanation using ONLY the "
        "provided headlines (if any) — you must clearly frame it as a possible/plausible cause, never as "
        "an established fact, and say so explicitly if no headlines were available. "
        "Structure your answer as: a 'FACT:' section stating the computed numbers, then a "
        "'POSSIBLE EXPLANATION:' section (only for notable-swing regions, hedged language). "
        "Do not give investment or credit recommendations. Keep it concise."
    )
    human = {
        "task": "Narrate the regional revenue picture, separating computed FACT from any POSSIBLE EXPLANATION.",
        "entity": entity,
        "region_metrics": region_metrics,
        "notable_regions": notable_regions,
        "news_by_region": {
            r: (d["data"]["articles"][:5] if d.get("status") == "OK" else {"unavailable_reason": d.get("reason")})
            for r, d in news_by_region.items()
        },
    }

    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0)
    messages = [SystemMessage(content=system), HumanMessage(content=json.dumps(human, indent=2, default=str))]
    resp = _db.instrumented_invoke(
        llm, messages, run_id=run_id, agent_name="geography_agent", model=model, base_url=base_url,
    )
    narrative = (getattr(resp, "content", "") or "").strip() or "(No narrative generated.)"

    return {
        "entity": entity,
        "status": "OK",
        "region_metrics": region_metrics,
        "notable_regions": notable_regions,
        "news_status_by_region": {r: d.get("status") for r, d in news_by_region.items()},
        "narrative": narrative,
    }
