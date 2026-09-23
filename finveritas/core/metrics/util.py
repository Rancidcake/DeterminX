"""Shared helpers for the deterministic metrics engine.

Mirrors the period-handling conventions already used by the V1 agents
(`src/revenue_agent.py`, `src/liquidity_agent.py`, `src/balance_sheet_agent.py`)
so the engine reads the exact same `entity` + `time_series` payload shape
without introducing a second parsing convention.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

_PERIOD_RE = re.compile(r"^(?P<year>\d{4})-(?P<tag>FY|Q[1-4])$")


def period_sort_key(period: str) -> tuple[int, int]:
    m = _PERIOD_RE.match(str(period).strip())
    if not m:
        # Tolerate malformed periods rather than crashing the whole engine —
        # they sort last and any metric depending on strict ordering will
        # simply see fewer usable periods.
        return (9999, 9)
    year = int(m.group("year"))
    tag = m.group("tag")
    return (year, 5) if tag == "FY" else (year, int(tag[1:]))


def series_map(payload: dict[str, Any], field_name: str) -> dict[str, float]:
    """{period -> value} for one canonical field, dropping null/NaN entries."""
    entries = (payload.get("time_series") or {}).get(field_name)
    if not isinstance(entries, list):
        return {}
    out: dict[str, float] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        p, v = e.get("period"), e.get("value")
        if not isinstance(p, str) or not p.strip() or v is None:
            continue
        try:
            vf = float(v)
        except (TypeError, ValueError):
            continue
        if np.isnan(vf):
            continue
        out[p.strip()] = vf
    return out


def all_periods(payload: dict[str, Any]) -> list[str]:
    periods: set[str] = set()
    for entries in (payload.get("time_series") or {}).values():
        if isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict) and e.get("period"):
                    periods.add(str(e["period"]))
    return sorted(periods, key=period_sort_key)


def entity_id(payload: dict[str, Any]) -> str:
    return str((payload.get("entity") or {}).get("entity_id") or "UNKNOWN")


def common_periods(payload: dict[str, Any], fields: list[str]) -> list[str]:
    """Periods where every field in `fields` has a value, chronologically sorted."""
    if not fields:
        return []
    maps = [series_map(payload, f) for f in fields]
    common = set(maps[0].keys())
    for m in maps[1:]:
        common &= set(m.keys())
    return sorted(common, key=period_sort_key)


def aligned_values(payload: dict[str, Any], field_name: str, periods: list[str]) -> list[float]:
    m = series_map(payload, field_name)
    return [m[p] for p in periods]


def yoy_growth_pct(values: list[float]) -> list[float | None]:
    """[None, g1, g2, ...] — percent growth vs the prior period, aligned to `values`."""
    out: list[float | None] = [None]
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev == 0:
            out.append(None)
            continue
        out.append((values[i] - prev) / abs(prev) * 100.0)
    return out


def cagr_pct(first: float, last: float, periods_elapsed: int) -> float | None:
    if periods_elapsed < 1 or first <= 0:
        return None
    return ((last / first) ** (1.0 / periods_elapsed) - 1.0) * 100.0


def linear_trend_direction(values: list[float]) -> str:
    """increasing/declining/stable, based on the sign+magnitude of the OLS
    slope normalised by the mean magnitude of the series — matches the
    threshold V1 agents already use (1% of mean per period)."""
    if len(values) < 2:
        return "stable"
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    slope = float(np.polyfit(x, y, deg=1)[0])
    scale = float(np.mean(np.abs(y))) or 1.0
    norm = slope / scale
    if norm > 0.01:
        return "increasing"
    if norm < -0.01:
        return "declining"
    return "stable"


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def mean(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return float(np.mean(vals)) if vals else None


def stdev(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return float(np.std(vals, ddof=0)) if len(vals) >= 2 else None


def latest_of(payload: dict[str, Any], field_name: str) -> tuple[str, float] | None:
    """(period, value) for the most recent period a field has data."""
    m = series_map(payload, field_name)
    if not m:
        return None
    p = sorted(m.keys(), key=period_sort_key)[-1]
    return p, m[p]


def field_present(payload: dict[str, Any], field_name: str) -> bool:
    return bool(series_map(payload, field_name))


# ---------------------------------------------------------------------------
# Fact-list builders — shared shape used by every category module so a metric
# that is available produces one CALCULATED Fact per period, and a metric
# that isn't produces a single explanatory UNAVAILABLE Fact instead of raising.
# ---------------------------------------------------------------------------

def period_facts(
    *, metric: str, category: str, periods: list[str], values: list[Any],
    unit: str, formula: str, source: str = "financial_statement",
    status: str = "CALCULATED",
) -> list:
    from metrics.schema import Fact, CALCULATED_BY

    facts = []
    for p, v in zip(periods, values):
        if v is None:
            continue
        facts.append(Fact(
            metric=metric, category=category, value=v, unit=unit, period=p,
            source=source, formula=formula, status=status,
            calculated_by=CALCULATED_BY,
            confidence="HIGH" if status == "CALCULATED" else "MEDIUM",
        ))
    return facts


def summary_fact(
    *, metric: str, category: str, value: Any, unit: str, formula: str,
    source: str = "financial_statement", status: str = "CALCULATED",
    warnings: tuple[str, ...] = (),
) -> Any:
    from metrics.schema import Fact, CALCULATED_BY

    return Fact(
        metric=metric, category=category, value=value, unit=unit,
        period="multi-period", source=source, formula=formula, status=status,
        calculated_by=CALCULATED_BY,
        confidence="HIGH" if status == "CALCULATED" else ("MEDIUM" if status == "ESTIMATED" else None),
        warnings=warnings,
    )


def latest_from_facts(facts: list, metric: str):
    """Find the most recent usable (CALCULATED/ESTIMATED) Fact for `metric` in
    a plain list of Facts — used when one category module needs a value another
    category already computed (e.g. domain.py reusing growth.py's revenue
    growth rate) without re-deriving it, per the 'single source of truth per
    metric' rule. Prefers a single-period fact over a multi-period summary
    unless only the summary exists."""
    candidates = [f for f in facts if f.metric == metric and f.status in ("CALCULATED", "ESTIMATED")]
    if not candidates:
        return None
    dated = [f for f in candidates if f.period not in (None, "multi-period")]
    pool = dated or candidates
    return sorted(pool, key=lambda f: f.period or "")[-1]


def missing_fields_fact(
    *, metric: str, category: str, missing: list[str], formula: str = "",
    status: str = "UNAVAILABLE",
) -> Any:
    from metrics.schema import Fact, CALCULATED_BY

    reason = f"Requires field(s) not present in ingested data: {', '.join(missing)}."
    return Fact(
        metric=metric, category=category, value=None, unit="", period=None,
        source="none", formula=formula, status=status, calculated_by=CALCULATED_BY,
        confidence=None, warnings=(reason,),
    )
