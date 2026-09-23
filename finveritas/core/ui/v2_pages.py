"""FinVeritas V2 — new dashboard pages.

Kept in its own module (rather than growing `app.py` further) so the V2
surface — Financial Metrics, Forecast, Competitive Intelligence, Risk &
Alerts, Credit Intelligence, Geography, Governance — is easy to find and
touch independently of the V1 page functions in `app.py`.

Every page here is a thin rendering layer: all numbers come from
`metrics.engine.build_fact_ledger` or one of the `src/<capability>` agents —
this module contains no financial arithmetic of its own.
"""

from __future__ import annotations

import hashlib
import html
import json
from typing import Any

import pandas as pd
import streamlit as st

from metrics.engine import build_fact_ledger
from metrics.schema import ALL_CATEGORIES, FactLedger
from ui.dashboard_components import render_hr, render_section_header

_STATUS_COLORS: dict[str, str] = {
    "CALCULATED": "#00FF88",
    "ESTIMATED": "#FFB000",
    "UNAVAILABLE": "#555566",
    "REQUIRES_EXTERNAL_DATA": "#00BFFF",
    "REQUIRES_ADDITIONAL_DOCUMENT": "#CC88FF",
    "PASS": "#00FF88",
    "WARN": "#FFB000",
    "FAIL": "#FF4444",
    "SKIP": "#555566",
    "OK": "#00FF88",
    "NOT_CONFIGURED": "#555566",
    "ERROR": "#FF4444",
}

_CATEGORY_LABELS: dict[str, str] = {
    "revenue": "Revenue", "cost": "Cost", "profitability": "Profitability",
    "liquidity": "Liquidity", "solvency": "Solvency", "debt_service": "Debt Servicing",
    "efficiency": "Efficiency", "returns": "Returns", "cash_flow": "Cash Flow",
    "growth": "Growth", "trend": "Trend", "risk": "Risk", "domain": "Domain-Specific",
}

# Sector -> [(domain_inputs key, form label), ...] — keys must match exactly
# what metrics/domain.py reads from payload["domain_inputs"].
_SECTOR_INPUT_FIELDS: dict[str, list[tuple[str, str]]] = {
    "saas": [
        ("sales_marketing_expense", "Sales & Marketing expense (period)"),
        ("new_customers", "New customers acquired (period)"),
        ("recurring_revenue", "Recurring revenue / ARR"),
        ("total_customers", "Total customers"),
        ("churn_rate_pct", "Customer churn rate (%)"),
        ("beginning_arr", "Beginning-of-period ARR"),
        ("expansion_revenue", "Expansion revenue (upsell/cross-sell)"),
        ("churned_revenue", "Churned revenue"),
    ],
    "banking": [
        ("interest_income", "Interest income"),
        ("interest_expense_on_funds", "Interest expense on funds"),
        ("avg_earning_assets", "Average earning assets"),
        ("gross_npa", "Gross NPA"),
        ("gross_advances", "Gross advances"),
        ("casa_deposits", "CASA deposits"),
        ("total_deposits", "Total deposits"),
        ("capital_adequacy_ratio_pct", "Capital Adequacy Ratio (%, as disclosed)"),
    ],
    "retail": [
        ("same_store_revenue_current", "Same-store revenue — current period"),
        ("same_store_revenue_prior", "Same-store revenue — prior period"),
        ("total_orders", "Total orders (period)"),
        ("retail_area_sqft", "Total retail area (sq ft)"),
    ],
    "manufacturing": [
        ("installed_capacity_units", "Installed capacity (units)"),
        ("actual_output_units", "Actual output (units)"),
        ("order_book_value", "Order book value"),
    ],
}


def status_badge(status: str) -> str:
    color = _STATUS_COLORS.get(status, "#888888")
    return (
        f'<span style="background:{color}22;color:{color};border:1px solid {color}66;'
        f'border-radius:3px;padding:1px 7px;font-size:9px;font-weight:700;'
        f'letter-spacing:0.06em;white-space:nowrap;">{html.escape(status)}</span>'
    )


def get_or_build_fact_ledger(
    payload: dict[str, Any], *, sector: str = "general", domain_inputs: dict[str, float] | None = None,
) -> FactLedger:
    """Cache the Fact Ledger in session_state, keyed by a hash of the ingested
    time_series (+ sector/domain_inputs, since those also change what the
    engine computes) so it's rebuilt only when something relevant changes."""
    domain_inputs = domain_inputs or {}
    cache_key = hashlib.sha256(json.dumps(
        {"ts": payload.get("time_series", {}), "sector": sector, "domain_inputs": domain_inputs},
        sort_keys=True, ensure_ascii=False,
    ).encode()).hexdigest()
    cached = st.session_state.get("fact_ledger_cache")
    if cached and cached.get("key") == cache_key:
        return cached["ledger"]
    enriched = dict(payload)
    enriched["sector"] = sector
    enriched["domain_inputs"] = domain_inputs
    ledger = build_fact_ledger(enriched)
    st.session_state["fact_ledger_cache"] = {"key": cache_key, "ledger": ledger}
    return ledger


def _safe_call(label: str, fn):
    """Run an agent call and surface any failure (e.g. LLM endpoint
    unreachable) as an `st.error`, mirroring app.py's `_safe_run` — a network
    failure in one V2 page must never crash the whole Streamlit script."""
    try:
        return fn()
    except Exception as exc:
        st.error(f"{label} failed: {exc}")
        return None


def _require_data() -> dict[str, Any] | None:
    cached = st.session_state.get("ocr_cache")
    if not cached:
        st.info("No financial data loaded yet. Go to **Upload Statement** first.")
        return None
    return cached["payload"]


def _facts_dataframe(ledger: FactLedger, category: str) -> pd.DataFrame:
    rows = []
    for f in ledger.by_category(category):
        rows.append({
            "Metric": f.metric.replace("_", " ").title(),
            "Period": f.period or "—",
            # Cast to str: a category can mix numeric facts with label facts
            # (e.g. revenue values alongside revenue_trend_direction="increasing"),
            # and a mixed-dtype column breaks Arrow serialisation in st.dataframe.
            "Value": str(round(f.value, 4)) if isinstance(f.value, float) else str(f.value),
            "Unit": f.unit,
            "Status": f.status,
            "Formula": f.formula,
            "Warnings": "; ".join(f.warnings) if f.warnings else "",
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Financial Metrics — 12-category dashboard (section 20)
# ─────────────────────────────────────────────────────────────────────────────

def page_financial_metrics() -> None:
    render_section_header(
        "Financial Metrics — Deterministic Engine",
        subtitle="Python computes every value below; status shows exactly why a metric is or isn't available",
    )
    payload = _require_data()
    if payload is None:
        return

    sector_labels = {
        "general": "General (no sector-specific metrics)",
        "saas": "SaaS / Software",
        "banking": "Banking / NBFC",
        "retail": "Retail / E-commerce",
        "manufacturing": "Manufacturing",
    }
    sector = st.selectbox(
        "Sector (adds domain-specific metrics — e.g. Rule of 40 / CAC / LTV for SaaS)",
        options=list(sector_labels.keys()), format_func=lambda k: sector_labels[k],
        key="fm_sector_select",
    )

    domain_inputs: dict[str, float] = {}
    fields = _SECTOR_INPUT_FIELDS.get(sector, [])
    if fields:
        with st.expander(
            f"Optional: {sector_labels[sector]} operational inputs "
            f"(unlocks CAC/LTV/NIM/etc. — these live outside any financial statement)",
        ):
            st.caption(
                "None of these figures can be derived from revenue/assets/liabilities — they're "
                "operational data (customer counts, churn, deposits, plant capacity, ...). Leave a "
                "field at 0 to skip it; that metric will show REQUIRES_ADDITIONAL_DOCUMENT instead "
                "of being guessed."
            )
            for key, label in fields:
                v = st.number_input(label, value=0.0, step=1.0, key=f"fm_domain_{sector}_{key}")
                if v:
                    domain_inputs[key] = v
        # A metric everyone already gets for free (Rule of 40) needs no inputs at all.
        if sector == "saas":
            st.caption("Rule of 40 and R&D Intensity are computed automatically from your loaded "
                       "financials even with no operational inputs entered above.")

    ledger = get_or_build_fact_ledger(payload, sector=sector, domain_inputs=domain_inputs)
    d = ledger.to_dict()

    cols = st.columns(5)
    cols[0].metric("Coverage", f"{d['coverage_pct']:.1f}%")
    cols[1].metric("Total Facts", len(d["facts"]))
    for i, status in enumerate(("CALCULATED", "ESTIMATED", "UNAVAILABLE")):
        cols[2 + i].markdown(
            f'<div style="font-size:10px;color:#888;">{status}</div>'
            f'<div style="font-size:20px;font-weight:700;">{d["status_summary"].get(status, 0)}</div>',
            unsafe_allow_html=True,
        )

    render_hr()
    tabs = st.tabs([_CATEGORY_LABELS[c] for c in ALL_CATEGORIES])
    for tab, category in zip(tabs, ALL_CATEGORIES):
        with tab:
            df = _facts_dataframe(ledger, category)
            if df.empty:
                st.caption("No facts produced for this category.")
                continue
            calc_df = df[df["Status"].isin(["CALCULATED", "ESTIMATED"])]
            gap_df = df[~df["Status"].isin(["CALCULATED", "ESTIMATED"])]
            if not calc_df.empty:
                st.dataframe(calc_df, use_container_width=True, hide_index=True)
            if not gap_df.empty:
                with st.expander(f"Not available ({len(gap_df)})", expanded=calc_df.empty):
                    st.dataframe(gap_df[["Metric", "Status", "Warnings"]], use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Forecast — assumption validation + forward projection (sections 4-7)
# ─────────────────────────────────────────────────────────────────────────────

def page_forecast(base_url: str, model: str, api_key: str) -> None:
    render_section_header(
        "Forecast — Assumption Validation & Projection",
        subtitle="Your assumption is checked against historical/guidance/benchmark references before it is projected",
    )
    payload = _require_data()
    if payload is None:
        return
    entity = payload["entity"]["entity_id"]
    ledger = get_or_build_fact_ledger(payload)

    metric_prefix = st.selectbox("Metric to forecast", ["revenue", "ebitda", "pat"], key="fc_metric")

    c1, c2, c3 = st.columns(3)
    assumption_pct = c1.number_input("Your growth assumption (%)", value=10.0, step=0.5, key="fc_assumption")
    guidance_low = c2.number_input("Management guidance — low (%)", value=0.0, step=0.5, key="fc_g_low")
    guidance_high = c3.number_input("Management guidance — high (%)", value=0.0, step=0.5, key="fc_g_high")

    c4, c5 = st.columns(2)
    sector_bench = c4.number_input("Sector/competitor benchmark (%, 0 = not entered)", value=0.0, step=0.5, key="fc_bench")
    country_code = c5.text_input("Country code for macro context (ISO2, optional)", value="", key="fc_country", max_chars=2)

    if st.button("▶  Validate & Forecast", key="fc_run_btn"):
        cfg_err = _llm_config_error_local(base_url, api_key)
        if cfg_err:
            st.error(f"LLM configuration error: {cfg_err}")
            return
        from src.forecast import assumption_validation_agent, forecast_engine

        with st.spinner("Validating assumption against reference data…"):
            validation = _safe_call("Assumption Validation Agent", lambda: assumption_validation_agent.run(
                entity=entity, ledger=ledger, user_assumption_pct=assumption_pct,
                metric_prefix=metric_prefix,
                guidance_low=guidance_low or None, guidance_high=guidance_high or None,
                sector_benchmark_pct=sector_bench or None, country_code=country_code or None,
                base_url=base_url, model=model, api_key=api_key,
            ))
        if validation is None:
            return
        st.session_state["fc_validation"] = validation

        with st.spinner("Projecting forward…"):
            forecast = _safe_call("Forecast Engine", lambda: forecast_engine.run(
                entity=entity, ledger=ledger, validation_result=validation,
                metric_prefix=metric_prefix, base_url=base_url, model=model, api_key=api_key,
            ))
        st.session_state["fc_forecast"] = forecast

    validation = st.session_state.get("fc_validation")
    forecast = st.session_state.get("fc_forecast")
    if not validation:
        return

    render_hr()
    render_section_header("Assumption Validation")
    verdict = validation["classification"]["verdict"]
    st.markdown(
        f'<div style="font-size:13px;">Verdict: {status_badge(verdict)} '
        f'&nbsp; deviation: {validation["classification"]["deviation_pp"]} pp</div>',
        unsafe_allow_html=True,
    )
    if validation["reference_points"]:
        st.dataframe(pd.DataFrame(validation["reference_points"]), use_container_width=True, hide_index=True)
    else:
        st.warning("No reference points were available — verdict is NO_REFERENCE_DATA.")

    with st.expander("External data source status"):
        st.json(validation["external_status"])

    st.markdown(f'<div class="bb-analysis">{html.escape(validation["explanation"]).replace(chr(10), "<br>")}</div>',
                unsafe_allow_html=True)

    if forecast and forecast.get("status") == "CALCULATED":
        render_hr()
        render_section_header("Forecast")
        st.dataframe(pd.DataFrame(forecast["projection"]), use_container_width=True, hide_index=True)
        st.markdown(f'<div class="bb-analysis">{html.escape(forecast["explanation"]).replace(chr(10), "<br>")}</div>',
                    unsafe_allow_html=True)
    elif forecast:
        st.warning(forecast.get("reason", "Forecast unavailable."))


# ─────────────────────────────────────────────────────────────────────────────
# Competitive Intelligence (sections 8-9)
# ─────────────────────────────────────────────────────────────────────────────

def page_competitive(base_url: str, model: str, api_key: str) -> None:
    render_section_header(
        "Competitive Intelligence",
        subtitle="Target vs peers — peer financials are fetched via yfinance and run through the same metrics engine",
    )
    payload = _require_data()
    if payload is None:
        return
    entity = payload["entity"]["entity_id"]
    ledger = get_or_build_fact_ledger(payload)

    peer_input = st.text_input(
        "Peer tickers (comma-separated, Yahoo Finance symbols)",
        placeholder="e.g. TCS.NS, WIPRO.NS, HCLTECH.NS", key="peer_tickers_input",
    )

    if st.button("▶  Run Competitive Benchmark", key="competitive_run_btn"):
        cfg_err = _llm_config_error_local(base_url, api_key)
        if cfg_err:
            st.error(f"LLM configuration error: {cfg_err}")
            return
        tickers = [t.strip() for t in peer_input.split(",") if t.strip()]
        if not tickers:
            st.warning("Enter at least one peer ticker.")
        else:
            from src.competitive import competitive_intelligence_agent
            with st.spinner(f"Fetching {len(tickers)} peer(s) and benchmarking…"):
                result = _safe_call("Competitive Intelligence Agent", lambda: competitive_intelligence_agent.run(
                    entity=entity, target_ledger=ledger, peer_tickers=tickers,
                    base_url=base_url, model=model, api_key=api_key,
                ))
            if result is not None:
                st.session_state["competitive_result"] = result

    result = st.session_state.get("competitive_result")
    if not result:
        return

    if result["status"] != "OK":
        st.warning(f"{result['status']}: {result.get('reason', '')}")
        return

    render_hr()
    rows = result["comparison"]["rows"]
    df = pd.DataFrame([
        {
            "Metric": r["metric"].replace("_", " ").title(),
            "Target": r.get("target_value"),
            "Peer Median": r.get("peer_median"),
            "Peer Average": r.get("peer_average"),
            "Gap vs Median": r.get("gap_vs_peer_median"),
            "Status": r["status"],
        }
        for r in rows
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    if result.get("peer_fetch_failures"):
        st.caption(f"Peers that failed to fetch: {result['peer_fetch_failures']}")

    render_hr()
    st.markdown(f'<div class="bb-analysis">{html.escape(result["narrative"]).replace(chr(10), "<br>")}</div>',
                unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Risk & Alerts — deterministic checks + anomaly scan (sections 2.12, 10)
# ─────────────────────────────────────────────────────────────────────────────

def page_risk_alerts() -> None:
    render_section_header(
        "Risk & Alerts",
        subtitle="Structural risk checks and anomaly detection vs the company's own history — all PASS/WARN/FAIL calls are deterministic",
    )
    payload = _require_data()
    if payload is None:
        return
    ledger = get_or_build_fact_ledger(payload)

    render_section_header("Risk Indicators (latest period)")
    risk_rows = []
    for f in ledger.by_category("risk"):
        risk_rows.append({
            "Check": f.metric.replace("_", " ").title(),
            "Status": f.status if f.status in ("PASS", "WARN", "FAIL") else f.status,
            "Detail": "; ".join(f.warnings) if f.warnings else "—",
        })
    if risk_rows:
        df = pd.DataFrame(risk_rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("No risk checks produced.")

    render_hr()
    render_section_header("Anomaly Alert System", subtitle="Current value vs the company's own historical range")
    from src.risk_monitoring.anomaly_engine import run_anomaly_scan
    scan = run_anomaly_scan(ledger)
    st.markdown(
        f'<div style="font-size:13px;">Overall: {status_badge(scan["overall_status"])} '
        f'&nbsp; PASS {scan["status_counts"]["PASS"]} · WARN {scan["status_counts"]["WARN"]} · '
        f'FAIL {scan["status_counts"]["FAIL"]} · SKIP {scan["status_counts"]["SKIP"]}</div>',
        unsafe_allow_html=True,
    )
    anomaly_df = pd.DataFrame([
        {
            "Metric": r["label"], "Status": r["status"], "Current": r["current_value"],
            "Historical Mean": r["historical_mean"], "Historical Range": r["historical_range"],
            "Z-Score": r["z_score"], "Detail": r["detail"],
        }
        for r in scan["results"]
    ])
    st.dataframe(anomaly_df, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Credit Intelligence — working capital / MPBF / DSCR (sections 11-14)
# ─────────────────────────────────────────────────────────────────────────────

def page_credit(base_url: str, model: str, api_key: str) -> None:
    render_section_header(
        "Credit Intelligence — Working Capital",
        subtitle="Tandon Method II style estimate — ALWAYS labelled estimated, never bank-grade MPBF/Drawing Power",
    )
    payload = _require_data()
    if payload is None:
        return
    entity = payload["entity"]["entity_id"]

    with st.expander("Optional: debt repayment schedule (enables precise DSCR)"):
        st.caption("Enter principal repayment due per period. Without this, DSCR is reported as requiring an additional document — never estimated.")
        periods = sorted({e["period"] for e in payload.get("time_series", {}).get("revenue", [])})
        schedule: dict[str, float] = {}
        for p in periods:
            v = st.number_input(f"Principal due — {p}", value=0.0, step=1.0, key=f"debt_sched_{p}")
            if v > 0:
                schedule[p] = v
        if schedule:
            payload = dict(payload)
            payload["debt_schedule"] = schedule

    if st.button("▶  Run Working Capital Analysis", key="credit_run_btn"):
        cfg_err = _llm_config_error_local(base_url, api_key)
        if cfg_err:
            st.error(f"LLM configuration error: {cfg_err}")
            return
        from metrics import debt_service
        from src.credit import working_capital_agent

        dscr_facts = debt_service.compute(payload)
        with st.spinner("Computing working capital position…"):
            result = _safe_call("Working Capital Agent", lambda: working_capital_agent.run(
                entity=entity, payload=payload, dscr_facts=dscr_facts,
                base_url=base_url, model=model, api_key=api_key,
            ))
        if result is not None:
            st.session_state["credit_result"] = result

    result = st.session_state.get("credit_result")
    if not result:
        return

    render_hr()
    facts = result["facts"]
    calc = [f for f in facts if f["status"] in ("CALCULATED", "ESTIMATED")]
    gap = [f for f in facts if f["status"] not in ("CALCULATED", "ESTIMATED")]

    df = pd.DataFrame([
        {"Metric": f["metric"].replace("_", " ").title(), "Period": f["period"] or "—",
         "Value": f["value"], "Unit": f["unit"], "Status": f["status"]}
        for f in calc
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    if gap:
        with st.expander(f"Not available / requires additional data ({len(gap)})"):
            st.dataframe(pd.DataFrame([
                {"Metric": f["metric"].replace("_", " ").title(), "Status": f["status"],
                 "Reason": "; ".join(f["warnings"])}
                for f in gap
            ]), use_container_width=True, hide_index=True)

    if result.get("dscr"):
        st.info(f"DSCR ({result['dscr']['period']}): {result['dscr']['value']}x")

    render_hr()
    st.markdown(f'<div class="bb-analysis">{html.escape(result["narrative"]).replace(chr(10), "<br>")}</div>',
                unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Geography (sections 15-16)
# ─────────────────────────────────────────────────────────────────────────────

def page_geography(base_url: str, model: str, api_key: str, news_api_key: str) -> None:
    render_section_header(
        "Geography-wise Impact Analysis",
        subtitle="Regional revenue/share/growth/volatility are Python-computed from figures you enter; news is used only to suggest a possible cause",
    )
    payload = _require_data()
    if payload is None:
        return
    entity = payload["entity"]["entity_id"]

    st.markdown("**Describe regional performance in your own words**")
    st.caption(
        "Type real, already-known figures in plain English — e.g. \"India revenue was ₹145bn in "
        "FY24 and ₹168bn in FY25, North America was roughly flat around ₹1,200bn both years.\" "
        "The model only transcribes the numbers you state into a table below for you to check — "
        "it does not estimate, invent, or reason about hypothetical figures. This is NOT a "
        "what-if / scenario-shock tool (that's explicitly out of scope for this deployment); "
        "everything you type must be a real number you already know."
    )
    scenario_text = st.text_area(
        "Scenario text", key="geo_scenario_text", height=90, label_visibility="collapsed",
        placeholder="e.g. India revenue was ₹145bn in FY24 and ₹168bn in FY25. Europe grew from "
                    "₹480bn to ₹512bn over the same period. North America declined slightly, "
                    "from ₹1,250bn to ₹1,180bn.",
    )
    if st.button("Parse scenario into a table", key="geo_parse_scenario_btn"):
        cfg_err = _llm_config_error_local(base_url, api_key)
        if cfg_err:
            st.error(f"LLM configuration error: {cfg_err}")
        elif not scenario_text.strip():
            st.warning("Type a scenario first.")
        else:
            from src.geography.scenario_parser import parse_scenario_text
            with st.spinner("Reading the numbers you described…"):
                parsed = _safe_call("Scenario Parser", lambda: parse_scenario_text(
                    text=scenario_text, base_url=base_url, model=model, api_key=api_key,
                ))
            if parsed is not None:
                st.session_state["geo_scenario_parsed"] = parsed

    parsed = st.session_state.get("geo_scenario_parsed")
    if parsed:
        for w in parsed.get("warnings", []):
            st.caption(f"⚠ {w}")
        if parsed.get("regions"):
            preview_rows = [
                {"Region": region, "Period": period, "Revenue": value}
                for region, periods in parsed["regions"].items()
                for period, value in periods.items()
            ]
            st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)
            st.caption("Source: LLM-assisted extraction from your typed text — review the numbers above before applying.")
            if st.button("✓  Looks right — apply to regional data below", key="geo_apply_scenario_btn"):
                manual = st.session_state.get("geo_manual_data", {})
                for region, periods in parsed["regions"].items():
                    manual.setdefault(region, {}).update(periods)
                st.session_state["geo_manual_data"] = manual
                st.session_state.pop("geo_scenario_parsed", None)
                st.success("Applied — scroll down to Regional Revenue to see it merged in, or run the analysis directly.")
                st.rerun()

    with st.expander("Or: best-effort extraction from pasted segment-note text"):
        raw_text = st.text_area("Paste the geographic segment disclosure text here", key="geo_raw_text", height=100)
        extract_period = st.text_input("Period this text refers to (e.g. 2024-FY)", key="geo_extract_period")
        if st.button("Extract regions from text", key="geo_extract_btn") and raw_text.strip() and extract_period.strip():
            from src.geography.geography_extractor import extract_regional_revenue
            found = extract_regional_revenue(raw_text, extract_period.strip())
            if found:
                st.session_state.setdefault("geo_manual_data", {})
                for region, val in found.items():
                    st.session_state["geo_manual_data"].setdefault(region, {})[extract_period.strip()] = val
                st.success(f"Extracted: {found}")
            else:
                st.warning("No recognisable region/value pairs found — enter data manually below.")

    render_hr()
    st.markdown("**Regional revenue** (region, period, value)")
    manual_data: dict[str, dict[str, float]] = st.session_state.get("geo_manual_data", {})
    n_rows = st.number_input("Number of region/period rows to enter", min_value=1, max_value=30, value=4, key="geo_n_rows")
    region_rows = []
    for i in range(int(n_rows)):
        c1, c2, c3 = st.columns(3)
        region = c1.text_input("Region", key=f"geo_region_{i}", value="")
        period = c2.text_input("Period", key=f"geo_period_{i}", value="")
        value = c3.number_input("Revenue", key=f"geo_value_{i}", value=0.0, step=1.0)
        if region.strip() and period.strip() and value:
            region_rows.append((region.strip(), period.strip(), value))

    for region, period, value in region_rows:
        manual_data.setdefault(region, {})[period] = value
    st.session_state["geo_manual_data"] = manual_data

    if st.button("▶  Run Geography Analysis", key="geo_run_btn"):
        cfg_err = _llm_config_error_local(base_url, api_key)
        if cfg_err:
            st.error(f"LLM configuration error: {cfg_err}")
            return
        from src.geography.geography_agent import run as run_geography
        total_revenue = {e["period"]: e["value"] for e in payload.get("time_series", {}).get("revenue", [])}
        with st.spinner("Analysing regional performance…"):
            result = _safe_call("Geography Agent", lambda: run_geography(
                entity=entity, regional_revenue=manual_data, total_revenue=total_revenue,
                news_api_key=news_api_key, base_url=base_url, model=model, api_key=api_key,
            ))
        if result is not None:
            st.session_state["geo_result"] = result

    result = st.session_state.get("geo_result")
    if not result:
        return

    render_hr()
    if result["status"] != "OK":
        st.warning(result.get("reason", "Unavailable."))
        return

    for region, m in result["region_metrics"].items():
        badge = " " + status_badge("NOTABLE SWING") if m["notable_swing"] else ""
        st.markdown(f"**{html.escape(region)}**{badge}", unsafe_allow_html=True)
        df = pd.DataFrame({
            "Period": m["periods"], "Revenue": m["revenue"],
            "Share %": m["revenue_share_pct"], "YoY Growth %": m["yoy_growth_pct"],
        })
        st.dataframe(df, use_container_width=True, hide_index=True)

    render_hr()
    st.markdown(f'<div class="bb-analysis">{html.escape(result["narrative"]).replace(chr(10), "<br>")}</div>',
                unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Governance (sections 17-18)
# ─────────────────────────────────────────────────────────────────────────────

def page_governance(base_url: str, model: str, api_key: str, news_api_key: str) -> None:
    render_section_header(
        "Governance — Executive Background",
        subtitle="Separate from financial health. Statutory registry lookups are NOT_CONFIGURED in this deployment (see src/external/governance_provider.py)",
    )
    payload = _require_data()
    if payload is None:
        return
    entity = payload["entity"]["entity_id"]

    with st.expander("Best-effort DIN extraction from pasted filing text (optional)"):
        raw_text = st.text_area("Paste director/board text here", key="gov_raw_text", height=100)
        if st.button("Extract directors from text", key="gov_extract_btn") and raw_text.strip():
            from src.governance.din_extractor import extract_directors
            found = extract_directors(raw_text)
            if found:
                st.session_state["gov_manual_directors"] = found
                st.success(f"Extracted {len(found)} director(s).")
            else:
                st.warning("No DIN/name pairs found — enter manually below.")

    directors: list[dict[str, str]] = st.session_state.get("gov_manual_directors", [{"name": "", "din": ""}])
    n_rows = st.number_input("Number of directors", min_value=1, max_value=20, value=max(1, len(directors)), key="gov_n_rows")
    rows = []
    for i in range(int(n_rows)):
        c1, c2 = st.columns(2)
        default_name = directors[i]["name"] if i < len(directors) else ""
        default_din = directors[i]["din"] if i < len(directors) else ""
        name = c1.text_input("Director name", value=default_name, key=f"gov_name_{i}")
        din = c2.text_input("DIN", value=default_din, key=f"gov_din_{i}")
        if name.strip() or din.strip():
            rows.append({"name": name.strip(), "din": din.strip()})

    if st.button("▶  Run Governance Check", key="gov_run_btn"):
        cfg_err = _llm_config_error_local(base_url, api_key)
        if cfg_err:
            st.error(f"LLM configuration error: {cfg_err}")
            return
        from src.governance.governance_agent import run as run_governance
        with st.spinner("Checking governance findings…"):
            result = _safe_call("Governance Agent", lambda: run_governance(
                entity=entity, directors=rows, news_api_key=news_api_key,
                base_url=base_url, model=model, api_key=api_key,
            ))
        if result is not None:
            st.session_state["gov_result"] = result

    result = st.session_state.get("gov_result")
    if not result:
        return

    render_hr()
    if result["status"] != "OK":
        st.warning(result.get("reason", "Unavailable."))
        return

    st.markdown(f'Overall governance status: {status_badge(result["overall_governance_status"])}',
                unsafe_allow_html=True)

    for f in result["findings"]:
        st.markdown(
            f'**{html.escape(f["name"])}** (DIN: {html.escape(f["din"])}) — {status_badge(f["status"])}',
            unsafe_allow_html=True,
        )
        st.caption(f'Statutory lookup: {f["statutory_lookup"]["status"]} — {f["statutory_lookup"].get("reason", "")}')
        matches = f["adverse_mention_screen"].get("matches") or []
        if matches:
            st.dataframe(pd.DataFrame(matches), use_container_width=True, hide_index=True)
        else:
            st.caption(f'{f["adverse_mention_screen"]["articles_scanned"]} article(s) scanned — no keyword matches.')

    render_hr()
    st.markdown(f'<div class="bb-analysis">{html.escape(result["narrative"]).replace(chr(10), "<br>")}</div>',
                unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Shared
# ─────────────────────────────────────────────────────────────────────────────

def _llm_config_error_local(base_url: str, api_key: str) -> str | None:
    """Local copy of app.py's `_llm_config_error` minimal check, kept in sync
    only for the "missing/placeholder key" case — the full provider-specific
    validation still lives in app.py and runs before these pages are reachable."""
    if not base_url or not base_url.strip():
        return "Missing LLM base URL. Configure it in the sidebar."
    if not api_key or api_key.strip().lower() in {"", "api key", "google ai studio key", "groq api key"}:
        return "Missing/placeholder LLM API key. Configure it in the sidebar."
    return None
