"""Forecast Engine (section 4/7 of the V2 brief).

Projects a metric forward using the user's assumption growth rate. The
projection arithmetic is pure Python (compounding); the LLM only writes the
causal "why" narrative from deterministically-derived driver observations
(recent-vs-historical growth trend, the assumption-validation verdict, and
the reference range) — it cannot alter the projected figures.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from metrics.schema import FactLedger
from metrics.util import period_sort_key
from src import db as _db


def project_series(*, latest_value: float, latest_period: str, growth_rate_pct: float, periods_ahead: int) -> list[dict[str, Any]]:
    """Pure compounding projection — deterministic, no LLM involved."""
    year = int(latest_period.split("-")[0]) if "-" in latest_period else None
    tag = latest_period.split("-")[1] if "-" in latest_period else "FY"
    out = []
    value = latest_value
    for i in range(1, periods_ahead + 1):
        value = value * (1 + growth_rate_pct / 100.0)
        period_label = f"{year + i}-{tag}" if year is not None else f"F+{i}"
        out.append({"period": period_label, "value": round(value, 4)})
    return out


def _growth_drivers(ledger: FactLedger, metric_prefix: str) -> list[str]:
    """Deterministic observations about the historical growth pattern, used
    verbatim as the LLM's only allowed 'why' inputs."""
    drivers: list[str] = []

    growth_facts = sorted(
        [f for f in ledger.by_metric(f"{metric_prefix}_growth") if f.period != "multi-period" and isinstance(f.value, (int, float))],
        key=lambda f: period_sort_key(f.period),
    )
    if len(growth_facts) >= 3:
        recent = [f.value for f in growth_facts[-2:]]
        earlier = [f.value for f in growth_facts[:-2]]
        if earlier:
            recent_avg = sum(recent) / len(recent)
            earlier_avg = sum(earlier) / len(earlier)
            if recent_avg < earlier_avg - 1.0:
                drivers.append(
                    f"historical growth has been decelerating (recent avg {recent_avg:.2f}% vs earlier avg {earlier_avg:.2f}%)"
                )
            elif recent_avg > earlier_avg + 1.0:
                drivers.append(
                    f"historical growth has been accelerating (recent avg {recent_avg:.2f}% vs earlier avg {earlier_avg:.2f}%)"
                )
            else:
                drivers.append(f"historical growth has been broadly stable (~{recent_avg:.2f}% recently)")

    trend = ledger.latest(f"{metric_prefix}_trend") or ledger.latest(f"{metric_prefix}_trend_direction")
    if trend and trend.status == "CALCULATED":
        drivers.append(f"the long-run trend classification is '{trend.value}'")

    return drivers


def run(
    *,
    entity: str,
    ledger: FactLedger,
    validation_result: dict[str, Any],
    periods_ahead: int = 3,
    metric_prefix: str = "revenue",
    base_url: str, model: str, api_key: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    latest_fact = ledger.latest(metric_prefix)
    if latest_fact is None or latest_fact.status != "CALCULATED" or not isinstance(latest_fact.value, (int, float)):
        return {
            "entity": entity, "metric": metric_prefix, "status": "UNAVAILABLE",
            "reason": f"No calculated latest-period value for '{metric_prefix}' in the fact ledger.",
        }

    assumption_pct = validation_result["user_assumption_pct"]
    projection = project_series(
        latest_value=float(latest_fact.value), latest_period=latest_fact.period,
        growth_rate_pct=assumption_pct, periods_ahead=periods_ahead,
    )

    drivers = _growth_drivers(ledger, metric_prefix)
    classification = validation_result["classification"]

    system = (
        "You are a financial forecasting analyst writing the causal 'why' behind an already-computed "
        "forecast. The forecast numbers and the assumption-validation verdict are FINAL and were computed "
        "in Python — you must not alter them, recompute them, or state different figures. "
        "Cite only the provided driver observations and verdict. Do not invent new drivers or data. "
        "Do not give investment or credit recommendations. Write 4-7 concise, professional sentences ending "
        "with one sentence assessing whether the forecast should be read as a base, optimistic, or "
        "conservative scenario relative to the reference range."
    )
    human = {
        "task": "Explain the causal reasoning behind this forecast using ONLY the provided drivers and verdict.",
        "entity": entity,
        "metric": metric_prefix,
        "assumption_growth_rate_pct": assumption_pct,
        "base_period": latest_fact.period,
        "base_value": latest_fact.value,
        "projection": projection,
        "growth_drivers": drivers,
        "validation_verdict": classification["verdict"],
        "reference_range": [classification["reference_low"], classification["reference_high"]],
    }

    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0)
    messages = [SystemMessage(content=system), HumanMessage(content=json.dumps(human, indent=2))]
    resp = _db.instrumented_invoke(
        llm, messages, run_id=run_id, agent_name="forecast_engine", model=model, base_url=base_url,
    )
    explanation = (getattr(resp, "content", "") or "").strip() or "(No explanation generated.)"

    return {
        "entity": entity,
        "metric": metric_prefix,
        "status": "CALCULATED",
        "base_period": latest_fact.period,
        "base_value": latest_fact.value,
        "assumption_growth_rate_pct": assumption_pct,
        "projection": projection,
        "growth_drivers": drivers,
        "validation_verdict": classification["verdict"],
        "reference_range": [classification["reference_low"], classification["reference_high"]],
        "explanation": explanation,
    }
