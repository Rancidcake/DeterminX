"""Assumption Validation Agent (section 5/6 of the V2 brief).

    User assumption -> reference data extraction -> Python normalization
        -> Python comparison -> deviation calculation -> risk/status
        -> LLM explanation

The comparison/classification is 100% deterministic Python. The LLM is
called afterward, given only the already-decided classification and the
numbers behind it, to explain *why* the assumption looks the way it does —
it cannot change ALIGNED to AGGRESSIVE or vice versa.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from metrics.schema import FactLedger
from src import db as _db
from src.external.guidance_provider import GuidanceProvider
from src.external.macro_provider import MacroProvider

VerdictType = str  # "ALIGNED" | "OPTIMISTIC" | "AGGRESSIVE" | "CAUTIOUS" | "OVERLY_CONSERVATIVE" | "NO_REFERENCE_DATA"

_OPTIMISTIC_BAND_PP = 5.0   # within this many points above the reference high -> OPTIMISTIC, not AGGRESSIVE
_ALIGNED_MARGIN_PP = 1.0    # tolerance around the reference range before flagging any deviation


@dataclass(frozen=True)
class ReferencePoint:
    label: str
    value_pct: float
    source: str


def _historical_references(ledger: FactLedger, metric_prefix: str) -> list[ReferencePoint]:
    refs: list[ReferencePoint] = []
    cagr = ledger.latest(f"{metric_prefix}_cagr")
    if cagr and cagr.status == "CALCULATED" and isinstance(cagr.value, (int, float)):
        refs.append(ReferencePoint(f"Historical {metric_prefix} CAGR", float(cagr.value), "financial_statement"))
    avg_growth = ledger.latest(f"{metric_prefix}_yoy_growth_avg")
    if avg_growth and avg_growth.status == "CALCULATED" and isinstance(avg_growth.value, (int, float)):
        refs.append(ReferencePoint(f"Historical avg YoY {metric_prefix} growth", float(avg_growth.value), "financial_statement"))
    return refs


def gather_reference_points(
    *,
    ledger: FactLedger,
    metric_prefix: str = "revenue",
    guidance_low: float | None = None,
    guidance_high: float | None = None,
    sector_benchmark_pct: float | None = None,
    country_code: str | None = None,
) -> dict[str, Any]:
    """Deterministically collect every available reference point. Each entry
    records its own status so the UI/LLM can see exactly what was and was not
    available — nothing here is invented when a source is missing."""

    references: list[ReferencePoint] = _historical_references(ledger, metric_prefix)
    external_status: dict[str, Any] = {}

    guidance_result = GuidanceProvider().fetch(low=guidance_low, high=guidance_high)
    external_status["management_guidance"] = guidance_result.to_dict()
    if guidance_result.ok:
        g = guidance_result.data
        if g["low"] is not None:
            references.append(ReferencePoint("Management guidance (low)", float(g["low"]), "management_guidance"))
        if g["high"] is not None:
            references.append(ReferencePoint("Management guidance (high)", float(g["high"]), "management_guidance"))

    if sector_benchmark_pct is not None:
        references.append(ReferencePoint("Sector/competitor benchmark (user-supplied)", float(sector_benchmark_pct), "user_input"))
        external_status["sector_benchmark"] = {"status": "OK", "value": sector_benchmark_pct, "source": "user_input"}
    else:
        external_status["sector_benchmark"] = {
            "status": "REQUIRES_EXTERNAL_DATA",
            "reason": "No sector-benchmark provider is configured; enter a value manually or via Competitive Intelligence peer results.",
        }

    if country_code:
        macro_result = MacroProvider().fetch(country_code=country_code)
        external_status["macro_gdp_growth"] = macro_result.to_dict()
        # Macro GDP growth is informational context, not a direct revenue-growth
        # reference point (it is never blended into the comparison band).
    else:
        external_status["macro_gdp_growth"] = {"status": "UNAVAILABLE", "reason": "No country code supplied."}

    external_status["analyst_estimates"] = {
        "status": "NOT_CONFIGURED",
        "reason": "No analyst-consensus provider is configured for this deployment.",
    }

    return {"references": references, "external_status": external_status}


def classify_assumption(
    *, user_assumption_pct: float, references: list[ReferencePoint],
) -> dict[str, Any]:
    """The deterministic core: Python decides ALIGNED/OPTIMISTIC/AGGRESSIVE/
    CAUTIOUS/OVERLY_CONSERVATIVE. This function is the only place that
    classification is ever decided."""
    if not references:
        return {
            "verdict": "NO_REFERENCE_DATA",
            "reference_low": None,
            "reference_high": None,
            "deviation_pp": None,
            "detail": "No historical, guidance, or benchmark reference points were available to validate against.",
        }

    values = [r.value_pct for r in references]
    ref_low, ref_high = min(values), max(values)

    if ref_low - _ALIGNED_MARGIN_PP <= user_assumption_pct <= ref_high + _ALIGNED_MARGIN_PP:
        verdict = "ALIGNED"
        deviation = 0.0
    elif user_assumption_pct > ref_high:
        deviation = user_assumption_pct - ref_high
        verdict = "OPTIMISTIC" if deviation <= _OPTIMISTIC_BAND_PP else "AGGRESSIVE"
    else:
        deviation = ref_low - user_assumption_pct
        verdict = "CAUTIOUS" if deviation <= _OPTIMISTIC_BAND_PP else "OVERLY_CONSERVATIVE"

    return {
        "verdict": verdict,
        "reference_low": round(ref_low, 3),
        "reference_high": round(ref_high, 3),
        "deviation_pp": round(deviation, 3),
        "detail": (
            f"User assumption {user_assumption_pct:.2f}% vs reference range "
            f"[{ref_low:.2f}%, {ref_high:.2f}%] built from {len(references)} reference point(s)."
        ),
    }


def _build_prompt(*, entity: str, metric_prefix: str, user_assumption_pct: float,
                   references: list[ReferencePoint], classification: dict[str, Any]) -> list[Any]:
    system = (
        "You are a financial forecasting analyst explaining an assumption-validation result. "
        "The verdict (ALIGNED/OPTIMISTIC/AGGRESSIVE/CAUTIOUS/OVERLY_CONSERVATIVE/NO_REFERENCE_DATA) "
        "has ALREADY been decided by a deterministic comparison — you must not change it, "
        "second-guess it, or state a different verdict. "
        "Do not compute, estimate, or infer any new numbers. Use only the provided values. "
        "Do not give investment or credit recommendations. Write 3-6 concise, professional sentences."
    )
    human = {
        "task": "Explain WHY the assumption received this verdict, referencing the specific reference points.",
        "entity": entity,
        "metric": metric_prefix,
        "user_assumption_pct": user_assumption_pct,
        "reference_points": [{"label": r.label, "value_pct": r.value_pct, "source": r.source} for r in references],
        "verdict": classification["verdict"],
        "reference_low": classification["reference_low"],
        "reference_high": classification["reference_high"],
        "deviation_pp": classification["deviation_pp"],
    }
    return [SystemMessage(content=system), HumanMessage(content=json.dumps(human, indent=2))]


def run(
    *,
    entity: str,
    ledger: FactLedger,
    user_assumption_pct: float,
    metric_prefix: str = "revenue",
    guidance_low: float | None = None,
    guidance_high: float | None = None,
    sector_benchmark_pct: float | None = None,
    country_code: str | None = None,
    base_url: str, model: str, api_key: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    ref_data = gather_reference_points(
        ledger=ledger, metric_prefix=metric_prefix,
        guidance_low=guidance_low, guidance_high=guidance_high,
        sector_benchmark_pct=sector_benchmark_pct, country_code=country_code,
    )
    references: list[ReferencePoint] = ref_data["references"]
    classification = classify_assumption(user_assumption_pct=user_assumption_pct, references=references)

    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0)
    messages = _build_prompt(
        entity=entity, metric_prefix=metric_prefix, user_assumption_pct=user_assumption_pct,
        references=references, classification=classification,
    )
    resp = _db.instrumented_invoke(
        llm, messages, run_id=run_id, agent_name="assumption_validation_agent",
        model=model, base_url=base_url,
    )
    explanation = (getattr(resp, "content", "") or "").strip() or "(No explanation generated.)"

    return {
        "entity": entity,
        "metric": metric_prefix,
        "user_assumption_pct": user_assumption_pct,
        "reference_points": [{"label": r.label, "value_pct": r.value_pct, "source": r.source} for r in references],
        "external_status": ref_data["external_status"],
        "classification": classification,
        "explanation": explanation,
    }
