"""Deterministic Financial Metrics Engine (FinVeritas V2).

Python computes -> Fact Ledger -> specialized agents -> LLM narrates.
No financial number produced here is ever overwritten downstream.

Public entry point: `metrics.engine.build_fact_ledger(payload)`.
"""

from metrics.schema import FactLedger, Fact  # noqa: F401
from metrics.engine import build_fact_ledger  # noqa: F401

__all__ = ["FactLedger", "Fact", "build_fact_ledger"]
