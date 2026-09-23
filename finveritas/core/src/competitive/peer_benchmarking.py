"""Deterministic peer benchmarking (section 9 of the V2 brief).

    Target Company -> Peer Data -> Normalize -> target / peer median / peer
    average / gap -> (LLM explains competitive position, elsewhere)

All numbers here are Python-computed from each company's own Fact Ledger —
peers are run through the exact same Deterministic Metrics Engine as the
target, so a "peer average EBITDA margin" is exactly as auditable as the
target's own.
"""

from __future__ import annotations

import statistics
from typing import Any

from metrics.schema import FactLedger

# (metric, category, unit label) — the benchmark set called out in section 8.
BENCHMARK_METRICS: list[tuple[str, str]] = [
    ("revenue_cagr", "%"),
    ("ebitda", "currency"),
    ("ebitda_margin", "%"),
    ("pat_cagr", "%"),
    ("roe", "%"),
    ("roce", "%"),
    ("debt_to_equity", "ratio"),
    ("net_profit_margin", "%"),
    ("gross_margin", "%"),
    ("asset_turnover", "turns/year"),
]


def _latest_numeric(ledger: FactLedger, metric: str) -> float | None:
    f = ledger.latest(metric)
    if f and f.status in ("CALCULATED", "ESTIMATED") and isinstance(f.value, (int, float)):
        return float(f.value)
    return None


def benchmark(
    *, target_name: str, target_ledger: FactLedger,
    peers: dict[str, FactLedger],
) -> dict[str, Any]:
    """Returns, per metric: target value, each peer's value, peer median,
    peer average, and gap (target - peer_median). Metrics unavailable for the
    target OR for every peer are reported with status UNAVAILABLE rather than
    silently dropped."""
    rows: list[dict[str, Any]] = []

    for metric, unit in BENCHMARK_METRICS:
        target_val = _latest_numeric(target_ledger, metric)
        peer_vals: dict[str, float] = {}
        for peer_name, peer_ledger in peers.items():
            v = _latest_numeric(peer_ledger, metric)
            if v is not None:
                peer_vals[peer_name] = v

        if target_val is None and not peer_vals:
            rows.append({
                "metric": metric, "unit": unit, "status": "UNAVAILABLE",
                "reason": "Not available for the target or any peer.",
            })
            continue

        peer_median = round(statistics.median(peer_vals.values()), 3) if peer_vals else None
        peer_average = round(statistics.mean(peer_vals.values()), 3) if peer_vals else None
        gap = round(target_val - peer_median, 3) if (target_val is not None and peer_median is not None) else None

        rows.append({
            "metric": metric, "unit": unit, "status": "CALCULATED" if target_val is not None else "PARTIAL",
            "target_value": target_val,
            "peer_values": peer_vals,
            "peer_median": peer_median,
            "peer_average": peer_average,
            "gap_vs_peer_median": gap,
        })

    return {"target": target_name, "peers": list(peers.keys()), "rows": rows}
