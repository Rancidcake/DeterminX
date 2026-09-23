"""Engine entry point — assembles the immutable Fact Ledger.

    Raw Data -> Normalization -> Deterministic Metrics Engine -> Fact Ledger

`build_fact_ledger` is the ONLY function downstream code should call. Each of
the 12 category modules is independent and pure (payload in, list[Fact] out);
a failure in one category is isolated so it can never take down the whole
ledger (it degrades to a single UNAVAILABLE fact explaining the failure,
which is itself useful diagnostic information for the UI/audit trail).
"""

from __future__ import annotations

import logging
from typing import Any

from metrics import (
    cash_flow, cost, debt_service, domain, efficiency, growth, liquidity,
    profitability, returns, revenue, risk, solvency, trends,
)
from metrics.schema import FactLedger, unavailable
from metrics.util import entity_id

logger = logging.getLogger(__name__)

_CATEGORY_MODULES = (
    ("revenue", revenue),
    ("cost", cost),
    ("profitability", profitability),
    ("liquidity", liquidity),
    ("solvency", solvency),
    ("debt_service", debt_service),
    ("efficiency", efficiency),
    ("returns", returns),
    ("cash_flow", cash_flow),
    ("growth", growth),
    ("trend", trends),
    ("risk", risk),
    ("domain", domain),
)


def build_fact_ledger(payload: dict[str, Any]) -> FactLedger:
    """Run every category module against the ingested payload and return the
    resulting Fact Ledger. Never raises for missing-data reasons — those
    surface as UNAVAILABLE facts, per section 21 of the V2 brief."""
    entity = entity_id(payload)
    ledger = FactLedger(entity=entity)

    for category, module in _CATEGORY_MODULES:
        try:
            facts = module.compute(payload)
            ledger.extend(facts)
        except Exception as exc:  # a bug in one category must not break the rest
            logger.exception("Metrics engine: category %r failed", category)
            ledger.add(unavailable(
                metric=f"{category}_category",
                category=category,
                reason=f"Internal error computing this category: {exc}",
            ))

    return ledger
