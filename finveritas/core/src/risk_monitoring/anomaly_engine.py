"""Anomaly Alert System — deterministic structural-ratio monitoring.

    current value vs historical pattern vs reference threshold -> PASS/WARN/FAIL

Every metric here already exists in the Fact Ledger (Solvency/Liquidity
categories); this module adds a second, independent lens: not "is this ratio
healthy in isolation" (that's `metrics/risk.py`) but "has this ratio moved
abnormally versus the company's OWN history". A metric can pass the
absolute-threshold check in `metrics/risk.py` and still fire a WARN/FAIL here
if it just broke sharply from its own historical range — that is the point
of continuous monitoring vs a one-time snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from metrics.schema import FactLedger
from metrics.util import mean, period_sort_key, stdev

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# (metric, label, higher_is_better) — the "structural ratios" called out in
# section 10. `higher_is_better=False` means a rising value is the risk
# direction (leverage-style); True means a falling value is the risk
# direction (coverage/liquidity-style).
_MONITORED_RATIOS: list[tuple[str, str, bool]] = [
    ("debt_to_equity", "Debt-to-Equity", False),
    ("equity_ratio", "Equity Ratio (Net Assets / (Debt + Equity))", True),
    ("current_ratio", "Current Ratio", True),
    ("net_debt_to_ebitda", "Net Debt / EBITDA", False),
    ("interest_coverage", "Interest Coverage", True),
]


@dataclass(frozen=True)
class AnomalyResult:
    metric: str
    label: str
    status: str
    current_period: str | None
    current_value: float | None
    historical_mean: float | None
    historical_range: tuple[float, float] | None
    z_score: float | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric, "label": self.label, "status": self.status,
            "current_period": self.current_period, "current_value": self.current_value,
            "historical_mean": self.historical_mean, "historical_range": self.historical_range,
            "z_score": self.z_score, "detail": self.detail,
        }


def _evaluate_one(metric: str, label: str, higher_is_better: bool, ledger: FactLedger) -> AnomalyResult:
    points = sorted(
        [f for f in ledger.by_metric(metric) if f.period != "multi-period" and isinstance(f.value, (int, float))
         and f.status in ("CALCULATED", "ESTIMATED")],
        key=lambda f: period_sort_key(f.period),
    )
    if len(points) < 4:
        return AnomalyResult(metric, label, "SKIP", None, None, None, None, None,
                              f"Need at least 4 periods to establish a historical range; found {len(points)}.")

    *historical, current = points
    hist_values = [p.value for p in historical]
    hmean = mean(hist_values)
    hstd = stdev(hist_values)
    hrange = (round(min(hist_values), 4), round(max(hist_values), 4))
    curr_val = current.value

    if hstd is None or hstd == 0:
        # No variance to compare against — fall back to range containment only.
        in_range = hrange[0] <= curr_val <= hrange[1]
        status = PASS if in_range else WARN
        detail = (
            f"{label} in {current.period} = {curr_val:.3g}; historical range "
            f"[{hrange[0]:.3g}, {hrange[1]:.3g}] (zero variance historically)."
        )
        return AnomalyResult(metric, label, status, current.period, curr_val, round(hmean, 4), hrange, None, detail)

    z = (curr_val - hmean) / hstd
    adverse_z = -z if higher_is_better else z  # positive adverse_z = moving the bad way

    if adverse_z >= 2.5:
        status = FAIL
    elif adverse_z >= 1.5:
        status = WARN
    else:
        status = PASS

    direction = "below" if curr_val < hmean else "above"
    detail = (
        f"{label} in {current.period} = {curr_val:.3g}, {abs(z):.2f} std-dev {direction} its own "
        f"historical mean of {hmean:.3g} (historical range [{hrange[0]:.3g}, {hrange[1]:.3g}])."
    )
    return AnomalyResult(metric, label, status, current.period, curr_val, round(hmean, 4), hrange, round(z, 3), detail)


def run_anomaly_scan(ledger: FactLedger) -> dict[str, Any]:
    """Evaluate every monitored structural ratio and return PASS/WARN/FAIL
    results plus an overall summary. Pure Python — no LLM involved here; the
    LLM explanation layer (if any) consumes this output but cannot alter it."""
    results = [_evaluate_one(metric, label, hib, ledger) for metric, label, hib in _MONITORED_RATIOS]

    counts = {PASS: 0, WARN: 0, FAIL: 0, "SKIP": 0}
    for r in results:
        counts[r.status] += 1

    overall = FAIL if counts[FAIL] > 0 else (WARN if counts[WARN] > 0 else PASS)

    return {
        "entity": ledger.entity,
        "overall_status": overall,
        "status_counts": counts,
        "results": [r.to_dict() for r in results],
    }
