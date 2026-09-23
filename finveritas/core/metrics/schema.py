"""Fact Ledger — the strict contract between the deterministic metrics engine
and every downstream agent (forecast, competitive, risk, credit, geography,
governance) and the LLM narration layer.

Core rule (V2 architecture, section 3): Python computes, the ledger records the
result as an immutable fact, and nothing downstream — no agent, no prompt, no
LLM — may overwrite a value once it is in the ledger. Agents read; they do not
recompute financial numbers independently.

Every metric carries an explicit availability state so the UI and the LLM can
distinguish a real calculation from a gap in the source data:

    CALCULATED                — computed directly from ingested statements
    ESTIMATED                 — computed using a simplifying assumption that
                                 must be disclosed (e.g. Tandon Method II NWC)
    UNAVAILABLE                — cannot be computed with the data on hand
    REQUIRES_EXTERNAL_DATA     — needs a provider (peer data, analyst
                                 estimates, governance registries, etc.)
    REQUIRES_ADDITIONAL_DOCUMENT — needs a document the user hasn't supplied
                                 (e.g. a debt repayment schedule for DSCR)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Status = Literal[
    "CALCULATED",
    "ESTIMATED",
    "UNAVAILABLE",
    "REQUIRES_EXTERNAL_DATA",
    "REQUIRES_ADDITIONAL_DOCUMENT",
]

STATUS_CALCULATED = "CALCULATED"
STATUS_ESTIMATED = "ESTIMATED"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_REQUIRES_EXTERNAL_DATA = "REQUIRES_EXTERNAL_DATA"
STATUS_REQUIRES_ADDITIONAL_DOCUMENT = "REQUIRES_ADDITIONAL_DOCUMENT"

# Categories — section 2 of the V2 brief.
CATEGORY_REVENUE = "revenue"
CATEGORY_COST = "cost"
CATEGORY_PROFITABILITY = "profitability"
CATEGORY_LIQUIDITY = "liquidity"
CATEGORY_SOLVENCY = "solvency"
CATEGORY_DEBT_SERVICE = "debt_service"
CATEGORY_EFFICIENCY = "efficiency"
CATEGORY_RETURNS = "returns"
CATEGORY_CASH_FLOW = "cash_flow"
CATEGORY_GROWTH = "growth"
CATEGORY_TREND = "trend"
CATEGORY_RISK = "risk"
CATEGORY_DOMAIN = "domain"

ALL_CATEGORIES = (
    CATEGORY_REVENUE, CATEGORY_COST, CATEGORY_PROFITABILITY, CATEGORY_LIQUIDITY,
    CATEGORY_SOLVENCY, CATEGORY_DEBT_SERVICE, CATEGORY_EFFICIENCY, CATEGORY_RETURNS,
    CATEGORY_CASH_FLOW, CATEGORY_GROWTH, CATEGORY_TREND, CATEGORY_RISK, CATEGORY_DOMAIN,
)

# Sectors the domain-specific metrics module (metrics/domain.py) understands.
# "general" means "no sector-specific metrics" — the default, zero behaviour change.
DOMAIN_SECTORS = ("general", "saas", "banking", "retail", "manufacturing")

CALCULATED_BY = "deterministic_metrics_engine"


@dataclass(frozen=True)
class Fact:
    """One authoritative financial fact.

    `value` is the number itself (or a qualitative label such as a trend
    direction / PASS-WARN-FAIL classification — those are still deterministic,
    not LLM opinion). `period` is a single fiscal period for a point-in-time
    metric, or "multi-period" for something summarising the whole series
    (e.g. CAGR, average ratio, trend classification).
    """

    metric: str
    category: str
    value: Any
    unit: str
    period: str | None
    source: str
    formula: str
    status: Status
    calculated_by: str = CALCULATED_BY
    confidence: str | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "category": self.category,
            "value": self.value,
            "unit": self.unit,
            "period": self.period,
            "source": self.source,
            "formula": self.formula,
            "status": self.status,
            "calculated_by": self.calculated_by,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
        }


def calculated(
    *, metric: str, category: str, value: Any, unit: str, period: str | None,
    formula: str, source: str = "financial_statement", confidence: str | None = "HIGH",
    warnings: tuple[str, ...] = (),
) -> Fact:
    return Fact(
        metric=metric, category=category, value=value, unit=unit, period=period,
        source=source, formula=formula, status=STATUS_CALCULATED,
        confidence=confidence, warnings=warnings,
    )


def estimated(
    *, metric: str, category: str, value: Any, unit: str, period: str | None,
    formula: str, source: str = "financial_statement", warnings: tuple[str, ...] = (),
) -> Fact:
    return Fact(
        metric=metric, category=category, value=value, unit=unit, period=period,
        source=source, formula=formula, status=STATUS_ESTIMATED,
        confidence="MEDIUM", warnings=warnings,
    )


def unavailable(
    *, metric: str, category: str, reason: str, period: str | None = None,
    formula: str = "", status: Status = STATUS_UNAVAILABLE,
) -> Fact:
    return Fact(
        metric=metric, category=category, value=None, unit="", period=period,
        source="none", formula=formula, status=status, confidence=None,
        warnings=(reason,),
    )


def requires_external(*, metric: str, category: str, reason: str, formula: str = "") -> Fact:
    return unavailable(
        metric=metric, category=category, reason=reason, formula=formula,
        status=STATUS_REQUIRES_EXTERNAL_DATA,
    )


def requires_document(*, metric: str, category: str, reason: str, formula: str = "") -> Fact:
    return unavailable(
        metric=metric, category=category, reason=reason, formula=formula,
        status=STATUS_REQUIRES_ADDITIONAL_DOCUMENT,
    )


@dataclass
class FactLedger:
    """Immutable-by-convention collection of Facts for one entity.

    Agents and the LLM layer MUST treat this as read-only. Nothing outside
    `metrics/engine.py` should construct or mutate a FactLedger.
    """

    entity: str
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    facts: list[Fact] = field(default_factory=list)

    def add(self, fact: Fact) -> None:
        self.facts.append(fact)

    def extend(self, facts: list[Fact]) -> None:
        self.facts.extend(facts)

    def by_category(self, category: str) -> list[Fact]:
        return [f for f in self.facts if f.category == category]

    def by_metric(self, metric: str) -> list[Fact]:
        """All periods for one metric, sorted by period (multi-period facts last)."""
        return sorted(
            (f for f in self.facts if f.metric == metric),
            key=lambda f: (f.period or "￿"),
        )

    def latest(self, metric: str) -> Fact | None:
        candidates = [f for f in self.facts if f.metric == metric and f.period not in (None, "multi-period")]
        if not candidates:
            candidates = [f for f in self.facts if f.metric == metric]
        if not candidates:
            return None
        return sorted(candidates, key=lambda f: f.period or "")[-1]

    def status_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for f in self.facts:
            summary[f.status] = summary.get(f.status, 0) + 1
        return summary

    def coverage_pct(self) -> float:
        """Share of facts that are CALCULATED or ESTIMATED (i.e. not blocked)."""
        if not self.facts:
            return 0.0
        ok = sum(1 for f in self.facts if f.status in (STATUS_CALCULATED, STATUS_ESTIMATED))
        return round(ok / len(self.facts) * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "generated_at": self.generated_at,
            "status_summary": self.status_summary(),
            "coverage_pct": self.coverage_pct(),
            "facts": [f.to_dict() for f in self.facts],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def for_llm(self, categories: list[str] | None = None) -> dict[str, Any]:
        """A trimmed view safe to hand to an LLM prompt: values + status only,
        no internal formula/source plumbing, restricted to CALCULATED/ESTIMATED
        facts (an LLM should never be asked to 'explain' a null)."""
        facts = self.facts if categories is None else [f for f in self.facts if f.category in categories]
        out: dict[str, list[dict[str, Any]]] = {}
        for f in facts:
            if f.status not in (STATUS_CALCULATED, STATUS_ESTIMATED):
                continue
            out.setdefault(f.category, []).append({
                "metric": f.metric, "value": f.value, "unit": f.unit,
                "period": f.period, "status": f.status,
            })
        return out
