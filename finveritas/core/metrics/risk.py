"""2.12 Risk Intelligence — deterministic structural risk indicators.

Every indicator resolves to a plain PASS / WARN / FAIL classification decided
entirely in Python. The LLM (in the risk-monitoring / anomaly agent layer)
may explain *why* a flag fired, but it never chooses the flag itself.
"""

from __future__ import annotations

from typing import Any

from metrics import util, debt_service
from metrics.schema import CATEGORY_RISK, Fact, unavailable

CATEGORY = CATEGORY_RISK

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def _status_fact(metric: str, status: str, detail: str, formula: str) -> Fact:
    return util.summary_fact(
        metric=metric, category=CATEGORY, value=status, unit="status",
        formula=formula, warnings=(detail,) if status != PASS else (),
    )


def compute(payload: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []

    # ── Negative EBITDA ──────────────────────────────────────────────────
    ebitda_map = util.series_map(payload, "ebitda")
    if not ebitda_map:
        op_map = util.series_map(payload, "operating_income")
        dep_map = util.series_map(payload, "depreciation")
        ebitda_map = {p: op_map[p] + dep_map[p] for p in set(op_map) & set(dep_map)}
    if ebitda_map:
        latest_p = sorted(ebitda_map.keys(), key=util.period_sort_key)[-1]
        v = ebitda_map[latest_p]
        status = FAIL if v < 0 else PASS
        facts.append(_status_fact("negative_ebitda_check", status,
                                   f"EBITDA in {latest_p} = {v:,.2f}" + (" (negative)" if v < 0 else ""),
                                   "FAIL if latest-period EBITDA < 0, else PASS"))
    else:
        facts.append(unavailable(metric="negative_ebitda_check", category=CATEGORY,
                                  reason="Requires 'ebitda' (or operating_income + depreciation)."))

    # ── Declining PAT ────────────────────────────────────────────────────
    ni_periods = util.common_periods(payload, ["net_income"])
    if len(ni_periods) >= 2:
        vals = util.aligned_values(payload, "net_income", ni_periods)
        declines = sum(1 for i in range(1, len(vals)) if vals[i] < vals[i - 1])
        share = declines / (len(vals) - 1)
        status = FAIL if vals[-1] < 0 or share >= 0.66 else (WARN if share >= 0.5 else PASS)
        facts.append(_status_fact("declining_pat_check", status,
                                   f"PAT declined in {declines}/{len(vals)-1} period-over-period comparisons; latest PAT = {vals[-1]:,.2f}",
                                   "FAIL if latest PAT<0 or PAT declined in >=66% of periods; WARN if >=50%; else PASS"))
    else:
        facts.append(unavailable(metric="declining_pat_check", category=CATEGORY,
                                  reason="Need at least 2 periods of 'net_income'."))

    # ── Margin Compression ───────────────────────────────────────────────
    nm_periods = util.common_periods(payload, ["revenue", "net_income"])
    if len(nm_periods) >= 2:
        rev = util.aligned_values(payload, "revenue", nm_periods)
        ni = util.aligned_values(payload, "net_income", nm_periods)
        margins = [n / r * 100 if r != 0 else None for n, r in zip(ni, rev)]
        margins_clean = [m for m in margins if m is not None]
        if len(margins_clean) >= 2:
            delta = margins_clean[-1] - margins_clean[0]
            status = FAIL if delta <= -5 else (WARN if delta < 0 else PASS)
            facts.append(_status_fact("margin_compression_check", status,
                                       f"Net margin moved from {margins_clean[0]:.2f}% to {margins_clean[-1]:.2f}% "
                                       f"({delta:+.2f} pp) across the available periods",
                                       "FAIL if net margin fell >=5pp end-to-end; WARN if it fell at all; else PASS"))
        else:
            facts.append(unavailable(metric="margin_compression_check", category=CATEGORY,
                                      reason="Revenue is zero in too many periods."))
    else:
        facts.append(unavailable(metric="margin_compression_check", category=CATEGORY,
                                  reason="Need at least 2 periods with both 'revenue' and 'net_income'."))

    # ── Rising Debt ──────────────────────────────────────────────────────
    debt_periods = util.common_periods(payload, ["total_debt"])
    if len(debt_periods) >= 2:
        vals = util.aligned_values(payload, "total_debt", debt_periods)
        growth = util.cagr_pct(vals[0], vals[-1], len(vals) - 1) if vals[0] > 0 else None
        if growth is None:
            facts.append(unavailable(metric="rising_debt_check", category=CATEGORY,
                                      reason="Cannot compute debt growth (non-positive starting value)."))
        else:
            status = FAIL if growth > 25 else (WARN if growth > 10 else PASS)
            facts.append(_status_fact("rising_debt_check", status,
                                       f"Total debt CAGR = {growth:.2f}% across the available periods",
                                       "FAIL if debt CAGR > 25%; WARN if > 10%; else PASS"))
    else:
        facts.append(unavailable(metric="rising_debt_check", category=CATEGORY,
                                  reason="Need at least 2 periods of 'total_debt'."))

    # ── Weak Current Ratio ───────────────────────────────────────────────
    cr_periods = util.common_periods(payload, ["current_assets", "current_liabilities"])
    if cr_periods:
        latest_p = cr_periods[-1]
        ca = util.series_map(payload, "current_assets")[latest_p]
        cl = util.series_map(payload, "current_liabilities")[latest_p]
        ratio = ca / cl if cl else None
        if ratio is None:
            facts.append(unavailable(metric="weak_current_ratio_check", category=CATEGORY,
                                      reason="current_liabilities is zero in the latest period."))
        else:
            status = FAIL if ratio < 1.0 else (WARN if ratio < 1.5 else PASS)
            facts.append(_status_fact("weak_current_ratio_check", status,
                                       f"Current ratio in {latest_p} = {ratio:.2f}",
                                       "FAIL if current ratio < 1.0; WARN if < 1.5; else PASS"))
    else:
        facts.append(unavailable(metric="weak_current_ratio_check", category=CATEGORY,
                                  reason="Requires 'current_assets' and 'current_liabilities'."))

    # ── Weak Interest Coverage ───────────────────────────────────────────
    ic_periods = util.common_periods(payload, ["operating_income", "interest_expense"])
    if ic_periods:
        latest_p = ic_periods[-1]
        op_inc = util.series_map(payload, "operating_income")[latest_p]
        ie = util.series_map(payload, "interest_expense")[latest_p]
        ratio = op_inc / ie if ie else None
        if ratio is None:
            facts.append(unavailable(metric="weak_interest_coverage_check", category=CATEGORY,
                                      reason="interest_expense is zero in the latest period."))
        else:
            status = FAIL if ratio < 1.5 else (WARN if ratio < 3.0 else PASS)
            facts.append(_status_fact("weak_interest_coverage_check", status,
                                       f"Interest coverage in {latest_p} = {ratio:.2f}x",
                                       "FAIL if interest coverage < 1.5x; WARN if < 3.0x; else PASS"))
    else:
        facts.append(unavailable(metric="weak_interest_coverage_check", category=CATEGORY,
                                  reason="Requires 'operating_income' and 'interest_expense'."))

    # ── Weak DSCR ────────────────────────────────────────────────────────
    dscr_facts = [f for f in debt_service.compute(payload) if f.metric == "dscr"]
    calculated_dscr = [f for f in dscr_facts if f.status == "CALCULATED"]
    if calculated_dscr:
        latest = sorted(calculated_dscr, key=lambda f: f.period or "")[-1]
        ratio = latest.value
        status = FAIL if ratio < 1.0 else (WARN if ratio < 1.25 else PASS)
        facts.append(_status_fact("weak_dscr_check", status,
                                   f"DSCR in {latest.period} = {ratio:.2f}x",
                                   "FAIL if DSCR < 1.0x; WARN if < 1.25x; else PASS"))
    else:
        facts.append(unavailable(
            metric="weak_dscr_check", category=CATEGORY,
            reason="DSCR requires a debt repayment schedule (see Debt Servicing Intelligence).",
            status="REQUIRES_ADDITIONAL_DOCUMENT",
        ))

    # ── Negative Operating Cash Flow ─────────────────────────────────────
    ocf_periods = util.common_periods(payload, ["operating_cash_flow"])
    if ocf_periods:
        latest_p = ocf_periods[-1]
        v = util.series_map(payload, "operating_cash_flow")[latest_p]
        status = FAIL if v < 0 else PASS
        facts.append(_status_fact("negative_ocf_check", status,
                                   f"Operating cash flow in {latest_p} = {v:,.2f}",
                                   "FAIL if latest-period operating cash flow < 0, else PASS"))
    else:
        facts.append(unavailable(metric="negative_ocf_check", category=CATEGORY,
                                  reason="Requires 'operating_cash_flow'."))

    # ── Abnormal Receivable Growth ───────────────────────────────────────
    ar_periods = util.common_periods(payload, ["accounts_receivable"])
    rev_periods = util.common_periods(payload, ["revenue"])
    common = sorted(set(ar_periods) & set(rev_periods), key=util.period_sort_key)
    if len(common) >= 2:
        ar_vals = util.aligned_values(payload, "accounts_receivable", common)
        rev_vals = util.aligned_values(payload, "revenue", common)
        ar_growth = util.cagr_pct(ar_vals[0], ar_vals[-1], len(ar_vals) - 1) if ar_vals[0] > 0 else None
        rev_growth = util.cagr_pct(rev_vals[0], rev_vals[-1], len(rev_vals) - 1) if rev_vals[0] > 0 else None
        if ar_growth is None or rev_growth is None:
            facts.append(unavailable(metric="abnormal_receivable_growth_check", category=CATEGORY,
                                      reason="Cannot compute growth (non-positive starting value)."))
        else:
            gap = ar_growth - rev_growth
            status = FAIL if gap > 20 else (WARN if gap > 10 else PASS)
            facts.append(_status_fact(
                "abnormal_receivable_growth_check", status,
                f"Receivables CAGR {ar_growth:.2f}% vs Revenue CAGR {rev_growth:.2f}% (gap {gap:+.2f}pp)",
                "FAIL if receivables CAGR exceeds revenue CAGR by >20pp; WARN if >10pp; else PASS",
            ))
    else:
        facts.append(unavailable(metric="abnormal_receivable_growth_check", category=CATEGORY,
                                  reason="Requires 'accounts_receivable' and 'revenue' for at least 2 overlapping periods."))

    return facts
