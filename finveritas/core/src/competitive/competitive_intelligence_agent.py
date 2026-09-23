"""Competitive Intelligence Agent (section 8 of the V2 brief).

Analyze Company X -> vs its peers/sector, instead of Company X in isolation.
Peer fetch + benchmarking are deterministic; the LLM only narrates the
resulting gaps.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from metrics.schema import FactLedger
from src import db as _db
from src.competitive.peer_benchmarking import benchmark
from src.external.peer_data_provider import PeerDataProvider


def run(
    *,
    entity: str,
    target_ledger: FactLedger,
    peer_tickers: list[str],
    base_url: str, model: str, api_key: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    provider_result = PeerDataProvider().fetch(tickers=peer_tickers)

    if not provider_result.ok:
        return {
            "entity": entity, "status": provider_result.status,
            "reason": provider_result.reason,
            "peer_tickers_requested": peer_tickers,
        }

    peer_ledgers: dict[str, FactLedger] = {}
    peer_meta: dict[str, Any] = {}
    for ticker, info in provider_result.data["peers"].items():
        fl = FactLedger(entity=info["entity"])
        from metrics.schema import Fact
        fl.facts = [Fact(**f) for f in info["fact_ledger"]["facts"]]
        peer_ledgers[info["entity"]] = fl
        peer_meta[info["entity"]] = {"ticker": ticker, "currency": info.get("currency")}

    comparison = benchmark(target_name=entity, target_ledger=target_ledger, peers=peer_ledgers)

    llm_rows = [r for r in comparison["rows"] if r["status"] in ("CALCULATED", "PARTIAL")]

    system = (
        "You are a competitive-intelligence analyst. Use ONLY the provided benchmark table — "
        "do not compute, estimate, or invent any new numbers, and do not fabricate peer figures. "
        "Explain where the target is stronger or weaker than the peer median/average and offer "
        "plausible (not certain) reasons, clearly framed as possible explanations rather than proven "
        "fact. Do not give investment or credit recommendations. Write 5-9 concise, professional sentences."
    )
    human = {
        "task": "Explain the target company's competitive position using ONLY the benchmark rows provided.",
        "entity": entity,
        "peers": comparison["peers"],
        "peer_ticker_map": peer_meta,
        "benchmark_rows": llm_rows,
        "failures": provider_result.data.get("failures", {}),
    }

    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0)
    messages = [SystemMessage(content=system), HumanMessage(content=json.dumps(human, indent=2))]
    resp = _db.instrumented_invoke(
        llm, messages, run_id=run_id, agent_name="competitive_intelligence_agent",
        model=model, base_url=base_url,
    )
    narrative = (getattr(resp, "content", "") or "").strip() or "(No narrative generated.)"

    return {
        "entity": entity,
        "status": "OK",
        "comparison": comparison,
        "peer_meta": peer_meta,
        "peer_fetch_failures": provider_result.data.get("failures", {}),
        "narrative": narrative,
    }
