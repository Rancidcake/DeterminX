"""Peer Data Provider — fetches peer-company financials for benchmarking.

Reuses the existing yfinance ingestion path (`src/yfinance_ingestion.py`) that
V1 already ships for the "Fetch by Ticker" tab — the V2 brief explicitly
calls for extending the existing multi-source ingestion architecture rather
than duplicating it (section 8). Each peer's payload is then run through the
same Deterministic Metrics Engine used for the target company, so peer
numbers are exactly as auditable as the target's.
"""

from __future__ import annotations

from typing import Any

from src.external.base import ExternalDataProvider, ProviderResult, error, ok, unavailable

PROVIDER_NAME = "yfinance_peers"
SOURCE_TYPE = "peer_financials"


class PeerDataProvider(ExternalDataProvider):
    name = PROVIDER_NAME
    source_type = SOURCE_TYPE

    def fetch(self, *, tickers: list[str]) -> ProviderResult:
        return self._guard(lambda: self._fetch(tickers))

    def _fetch(self, tickers: list[str]) -> ProviderResult:
        from metrics.engine import build_fact_ledger
        from src.yfinance_ingestion import fetch_by_ticker

        clean = [t.strip() for t in tickers if t and t.strip()]
        if not clean:
            return unavailable(self.name, self.source_type, "No peer tickers supplied.")

        peers: dict[str, Any] = {}
        failures: dict[str, str] = {}
        for ticker in clean:
            try:
                payload = fetch_by_ticker(ticker)
                ledger = build_fact_ledger(payload)
                peers[ticker] = {
                    "entity": payload["entity"]["entity_id"],
                    "currency": payload["entity"].get("currency"),
                    "fact_ledger": ledger.to_dict(),
                }
            except Exception as exc:
                failures[ticker] = str(exc)

        if not peers:
            return error(self.name, self.source_type,
                         f"Could not fetch any peer data. Failures: {failures}")

        return ok(self.name, self.source_type, {"peers": peers, "failures": failures},
                   raw_reference=f"yfinance tickers: {', '.join(peers.keys())}")
