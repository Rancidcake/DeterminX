# Knowledge Transfer — V2: Explainable Financial Intelligence

**Project:** FinVeritas — Explainable Financial Analysis Platform
**Audience:** Developer or analyst picking up the codebase cold
**Scope:** Everything added on top of V1 (Deterministic Metrics Engine, Forecasting, Competitive
Intelligence, Risk/Anomaly Monitoring, Credit Intelligence, Geography, Governance) plus the new
sidebar pages that expose them.

---

## 0. Core principle (unchanged from V1, load-bearing for all of V2)

> **Python computes. The LLM only narrates.** No financial number is ever produced by a model call.

Every new capability below follows the exact same two-step shape V1's five agents already used:

```
raw payload (entity + time_series)
        │
        ▼
  deterministic Python function  ──► number / verdict / classification
        │
        ▼
  LLM call, given ONLY the already-decided numbers  ──► narration text
```

The LLM is structurally incapable of changing a number it's handed — it receives a dict of
pre-computed values in the `HumanMessage` and a system prompt that says "do not compute, estimate,
or infer any new numbers." If a value can't be computed, the pipeline reports **why**, in Python,
before the LLM is even called — it never asks the LLM to fill a gap.

### New top-level architecture

```
Raw Data Sources (unchanged V1 ingestion: Bloomberg PDF / yfinance / CSV / AA)
        │
        ▼
Deterministic Financial Metrics Engine  (metrics/)         ← NEW, section 1
        │
        ▼
Immutable Fact Ledger  (metrics/schema.py::FactLedger)      ← NEW, the central contract
        │
   ┌────┼────────────┬──────────────┬───────────────┬───────────────┐
   ▼    ▼             ▼              ▼               ▼               ▼
Forecast  Competitive  Risk/Anomaly  Credit/Working   Geography      Governance
(src/forecast/)  (src/competitive/)  Capital           (src/geography/) (src/governance/)
                 (src/risk_monitoring/) (src/credit/)
   │              │             │              │               │               │
   └──────────────┴─────────────┴──────────────┴───────────────┴───────────────┘
                                      │
                                      ▼
                        External Data Layer (src/external/)
                    peer data · macro · guidance · news · [analyst estimates,
                    governance registries — both explicitly NOT_CONFIGURED]
                                      │
                                      ▼
                        ui/v2_pages.py — 7 new Streamlit pages
```

---

## 1. Deterministic Financial Metrics Engine — `metrics/`

### What it is

The foundation everything else sits on. Twelve category modules, each a pure function
`compute(payload: dict) -> list[Fact]`, run by `metrics/engine.py::build_fact_ledger(payload)`
against the **same** `entity` + `time_series` payload shape V1's OCR/yfinance/CSV ingestion already
produces — no ingestion pipeline was replaced.

### Where it lives

| What | File | Key symbol |
|---|---|---|
| `Fact` / `FactLedger` schema, status constants | `core/metrics/schema.py` | `Fact` — L68, `FactLedger` — L155 |
| Shared period/series helpers + Fact builders | `core/metrics/util.py` | `period_facts()`, `summary_fact()`, `missing_fields_fact()` |
| Engine entry point | `core/metrics/engine.py` | `build_fact_ledger()` — L42 |
| Revenue Intelligence | `core/metrics/revenue.py` | `compute()` |
| Cost Intelligence | `core/metrics/cost.py` | `compute()` |
| Profitability Intelligence | `core/metrics/profitability.py` | `compute()` |
| Liquidity Intelligence | `core/metrics/liquidity.py` | `compute()` |
| Solvency Intelligence | `core/metrics/solvency.py` | `compute()` |
| Debt Servicing Intelligence (DSCR) | `core/metrics/debt_service.py` | `compute()` — L36 |
| Efficiency Intelligence | `core/metrics/efficiency.py` | `compute()` |
| Return Intelligence | `core/metrics/returns.py` | `compute()` |
| Cash Flow Intelligence | `core/metrics/cash_flow.py` | `compute()` |
| Growth Intelligence | `core/metrics/growth.py` | `compute()` |
| Trend Intelligence | `core/metrics/trends.py` | `compute()` |
| Risk Intelligence (PASS/WARN/FAIL) | `core/metrics/risk.py` | `compute()` — L27 |

### The `Fact` contract

```python
@dataclass(frozen=True)
class Fact:
    metric: str            # e.g. "ebitda_margin"
    category: str          # one of the 12 categories
    value: Any              # number, or a label ("increasing"), or "PASS"/"WARN"/"FAIL"
    unit: str               # "%", "ratio", "days", "INR", "label", "status"
    period: str | None      # "2026-FY", or "multi-period" for a summary stat (CAGR, trend, ...)
    source: str              # "financial_statement", "derived", "user_input", ...
    formula: str              # human-readable derivation — always populated
    status: Status             # CALCULATED / ESTIMATED / UNAVAILABLE /
                                 # REQUIRES_EXTERNAL_DATA / REQUIRES_ADDITIONAL_DOCUMENT
    calculated_by: str = "deterministic_metrics_engine"
    confidence: str | None = None
    warnings: tuple[str, ...] = ()
```

Every category module follows the same defensive pattern — try the direct field, fall back to a
disclosed derivation (marked `ESTIMATED`, formula says exactly what was derived from what), and if
neither is possible, emit a single `unavailable(...)` Fact with a plain-English reason instead of
raising or guessing:

```python
# metrics/profitability.py — EBITDA fallback, real snippet
ebitda_periods = util.common_periods(payload, ["ebitda"])
if ebitda_periods:
    ebitda_formula = "As reported"
else:
    ebitda_periods = util.common_periods(payload, ["operating_income", "depreciation"])
    ebitda_status = "ESTIMATED"
    ebitda_formula = "Operating Income + Depreciation & Amortization (derived)"
```

`metrics/engine.py::build_fact_ledger()` wraps each of the 12 modules in its own try/except — one
category throwing a bug never takes down the other 11; it degrades to a single diagnostic
`UNAVAILABLE` fact for that category instead.

### What the analyst sees — real output (TCS.NS, live yfinance data, run 2026-09-24)

```
coverage_pct: 95.6
status_summary: {'CALCULATED': 224, 'UNAVAILABLE': 9, 'ESTIMATED': 16, 'REQUIRES_ADDITIONAL_DOCUMENT': 2}

Profitability category (FY2026):
  gross_profit       = 1,096,410,000,000  [CALCULATED]  INR
  gross_margin       = 42.94%             [CALCULATED]
  ebitda             = 675,350,000,000    [ESTIMATED]   INR   (derived: EBIT + Depreciation)
  ebitda_margin      = 26.45%             [ESTIMATED]
  operating_margin   = 24.40%             [CALCULATED]
  net_profit_margin  = 19.02%             [CALCULATED]

Honest gaps (no fabrication):
  net_sales               [UNAVAILABLE]  "Not tracked as a field distinct from 'revenue' by
                                           the current ingestion schema."
  rd_expense               [UNAVAILABLE]  "No 'rd_expense' time series present in ingested data."
  eps                       [UNAVAILABLE]  "Requires 'basic_eps'."
```

This is the exact shape the brief's section 21 ("data availability must be first-class") asked for —
every gap says *why*, not just "N/A".

### DSCR — the one metric that is never guessed (section 13/14 of the brief)

`metrics/debt_service.py::compute()` only produces a `dscr` Fact if the caller supplies
`payload["debt_schedule"] = {period: principal_repayment_due}`. Absent that, it returns
`REQUIRES_ADDITIONAL_DOCUMENT`, never an estimate:

```python
schedule = _debt_schedule(payload)
if not schedule:
    facts.append(requires_document(
        metric="dscr", category=CATEGORY,
        reason=("Precise DSCR requires a debt repayment/maturity schedule ... "
                "it will not be estimated from the income statement alone."),
        formula="(PAT + Depreciation + Interest) / (Principal Repayment + Interest)",
    ))
    return facts
```

`metrics/risk.py::compute()`'s `weak_dscr_check` reuses this same function rather than
re-implementing the check, so there is exactly one place DSCR logic lives.

---

## 2. Ingestion schema extended (still V1 files, purely additive)

New canonical fields needed by the metrics engine but not in V1's original field set:
`sga_expense`, `rd_expense`, `amortization`, `inventory`, `accounts_receivable`,
`accounts_payable`, `operating_cash_flow`, `investing_cash_flow`, `financing_cash_flow`, `capex`.

| File | What changed |
|---|---|
| `core/src/mapper.py` | New regex patterns for the fields above under Bloomberg PDF line-item labels — appended, no existing pattern touched |
| `core/src/yfinance_ingestion.py` | New `_CASHFLOW_MAP`, extended `_INCOME_MAP`/`_BALANCE_MAP`, now also pulls `t.cashflow` |
| `core/src/private_company_ingestion.py` | New fields added to `_CANONICAL_FIELDS`; `get_template_csv()` now emits them as extra columns |
| `core/src/supplemental_fetchers.py` | See §9 below — also picks up `inventory`/`accounts_receivable`/`accounts_payable` from FMP and Alpha Vantage |

Regression-verified: every existing V1 label (`"Total Revenue"`, `"Net Income"`, `"Cost of Goods
Sold"`, …) still resolves to exactly the same canonical key as before.

---

## 3. External Data Layer — `src/external/`

### What it is

One abstraction every external dependency sits behind, so business logic never talks to a vendor
SDK directly (brief section 22/17: "do not hard-code around one scraping implementation").

| Provider | File | Status in this deployment |
|---|---|---|
| Peer financials | `peer_data_provider.py` | **Live** — reuses `yfinance_ingestion.fetch_by_ticker` + the metrics engine, so peer numbers are exactly as auditable as the target's |
| Macro indicators (GDP growth, inflation) | `macro_provider.py` | **Live** — World Bank Open Data, free/keyless |
| Management guidance | `guidance_provider.py` | **Live** — user-entered only, FinVeritas does not transcribe earnings calls |
| News | `news_provider.py` | **Live** — wraps V1's existing `src/sentiment_agent.py::fetch_news`, reused for Geography + Governance |
| Analyst consensus estimates | `analyst_estimates_provider.py` | `NOT_CONFIGURED` — no licensed feed (I/B/E/S, Visible Alpha, Bloomberg) is available |
| Governance registries (MCA/SEBI/IBBI) | `governance_provider.py` | `NOT_CONFIGURED` — no public keyless API exists for these |

### The contract (`base.py`)

```python
@dataclass(frozen=True)
class ProviderResult:
    provider: str
    source_type: str
    status: str        # OK / UNAVAILABLE / ERROR / NOT_CONFIGURED
    data: Any = None
    reason: str | None = None
    retrieved_at: str = ...     # ISO timestamp, auto-filled
    raw_reference: str | None = None
```

Every provider extends `ExternalDataProvider` and implements `fetch(**kwargs) -> ProviderResult`;
`ExternalDataProvider._guard()` catches any network/library exception and turns it into
`status="ERROR"` instead of letting it propagate — callers never need their own try/except around a
provider call.

---

## 4. Forecast — Assumption Validation Agent — `src/forecast/`

### What it is

> User assumption → reference data → Python comparison → verdict → LLM explains *why*.

`assumption_validation_agent.py::classify_assumption()` is the **only** place a verdict is decided
— it's pure Python, no LLM call inside it:

```python
if ref_low - _ALIGNED_MARGIN_PP <= user_assumption_pct <= ref_high + _ALIGNED_MARGIN_PP:
    verdict = "ALIGNED"
elif user_assumption_pct > ref_high:
    deviation = user_assumption_pct - ref_high
    verdict = "OPTIMISTIC" if deviation <= _OPTIMISTIC_BAND_PP else "AGGRESSIVE"
else:
    deviation = ref_low - user_assumption_pct
    verdict = "CAUTIOUS" if deviation <= _OPTIMISTIC_BAND_PP else "OVERLY_CONSERVATIVE"
```

`forecast_engine.py::project_series()` then compounds the *user's own validated rate* forward — pure
arithmetic, no LLM. `forecast_engine.py::_growth_drivers()` deterministically classifies whether
recent growth is accelerating/decelerating (comparing the last-2-periods average vs. the earlier
average) — these driver strings are the **only** "why" material the LLM is allowed to cite.

### Where it lives

| What | File | Key symbol |
|---|---|---|
| Reference-point gathering | `src/forecast/assumption_validation_agent.py` | `gather_reference_points()` — L51 |
| Deterministic verdict | `src/forecast/assumption_validation_agent.py` | `classify_assumption()` — L101 |
| Agent orchestration + LLM call | `src/forecast/assumption_validation_agent.py` | `run()` — L165 |
| Pure compounding projection | `src/forecast/forecast_engine.py` | `project_series()` — L23 |
| Deterministic growth-driver detection | `src/forecast/forecast_engine.py` | `_growth_drivers()` — L36 |

### What the analyst sees — real output (TCS.NS, assumption = 18% revenue growth)

```
verdict: AGGRESSIVE
  User assumption 18.00% vs reference range [5.80%, 11.00%] built from 4 reference point(s)
  reference points:
    Historical revenue CAGR          = 5.80%   (financial_statement)
    Historical avg YoY revenue growth = 5.81%  (financial_statement)
    Management guidance (low)         = 9.0%   (management_guidance)
    Management guidance (high)        = 11.0%  (management_guidance)

LLM explanation:
  "The assumption of an 18% revenue growth rate is well above all of the reference points for
   Tata Consultancy Services. It exceeds the historical revenue CAGR of 5.80% ... and surpasses
   the upper bound of management's guidance, which tops out at 11.0% ... the deterministic
   comparison classifies the assumption as AGGRESSIVE."

Forecast (deterministic compounding at the user's 18% rate):
  2027-FY: ₹3,150,847,800,000
  2028-FY: ₹3,718,000,404,000
  2029-FY: ₹4,387,240,476,720

Growth drivers handed to the LLM (computed in Python, not observed by it):
  "historical growth has been decelerating (recent avg 4.58% vs earlier avg 6.42%)"
  "the long-run trend classification is 'increasing'"

LLM's forecast narration:
  "... This rate is markedly higher than the recent historical average of 4.58% (down from an
   earlier 6.42%), indicating a departure from the observed deceleration. ... Accordingly, the
   forecast should be read as an optimistic scenario relative to the reference range."
```

Note the LLM never states a number that isn't in the driver/reference dict it was handed — it's
mechanically prevented from inventing a different CAGR or a different projected revenue figure.

---

## 5. Competitive Intelligence — `src/competitive/`

### What it is

> Analyze Company X → vs. its peers, not in isolation.

`peer_benchmarking.py::benchmark()` computes target value / peer values / peer median / peer average
/ gap for 10 metrics (Revenue CAGR, EBITDA, EBITDA Margin, PAT CAGR, ROE, ROCE, Debt-to-Equity, Net
Margin, Gross Margin, Asset Turnover) — entirely in Python, using `statistics.median`/`mean`. Peers
are fetched via `PeerDataProvider` (§3), which runs each peer through the **same**
`metrics.engine.build_fact_ledger()` the target uses.

### Where it lives

| What | File | Key symbol |
|---|---|---|
| The 10-metric benchmark set | `src/competitive/peer_benchmarking.py` | `BENCHMARK_METRICS` |
| Deterministic comparison | `src/competitive/peer_benchmarking.py` | `benchmark()` — L41 |
| Orchestration + LLM narration | `src/competitive/competitive_intelligence_agent.py` | `run()` — L22 |

### What the analyst sees — real output (TCS.NS vs INFY.NS, WIPRO.NS peers)

```
metric               target        peer_median      gap
revenue_cagr          5.80%          2.11%          +3.69pp
ebitda                ₹725.82bn      ₹91.44bn        +₹634.38bn
ebitda_margin          27.18%         21.13%          +6.05pp
roe                     45.89%         24.38%          +21.51pp
roce                    55.18%         26.04%          +29.14pp
debt_to_equity           0.689          0.637          +0.052
asset_turnover           1.562         0.938           +0.624

LLM narrative (excerpt):
  "TCS posts a revenue CAGR of 5.8% — well above the peer median of 2.1% — which may reflect
   its broader geographic footprint... Return-on-equity (45.9%) and return-on-capital-employed
   (55.2%) are markedly superior to the peer median (24.4% and 26.0%)... However, TCS's
   debt-to-equity ratio of 0.689 is modestly higher than the peer median of 0.637, suggesting
   slightly greater leverage that may be tied to recent strategic acquisitions..."
```

---

## 6. Risk & Anomaly Alert System — `src/risk_monitoring/` + `metrics/risk.py`

### What it is

Two independent, complementary lenses, both deterministic:

1. **`metrics/risk.py`** — absolute-threshold checks (does this ratio look unhealthy on its own
   terms?): negative EBITDA, declining PAT, margin compression, rising debt, weak current ratio,
   weak interest coverage, weak DSCR, negative operating cash flow, abnormal receivable growth.
2. **`src/risk_monitoring/anomaly_engine.py`** — continuous monitoring (has this ratio moved
   *abnormally versus the company's own history*?), extending V1's `data_verifier.py` PASS/WARN/FAIL
   pattern rather than duplicating it.

### The anomaly z-score logic (real code)

```python
*historical, current = points   # all periods except the latest, then the latest
hmean = mean(hist_values); hstd = stdev(hist_values)
z = (curr_val - hmean) / hstd
adverse_z = -z if higher_is_better else z   # positive adverse_z = moving the "bad" way
if adverse_z >= 2.5:  status = FAIL
elif adverse_z >= 1.5: status = WARN
else:                  status = PASS
```

Needs ≥ 4 historical periods to establish a range; below that it reports `SKIP`, never a guess.

### Where it lives

| What | File | Key symbol |
|---|---|---|
| Absolute-threshold risk checks | `core/metrics/risk.py` | `compute()` — L27 |
| Own-history anomaly scan | `core/src/risk_monitoring/anomaly_engine.py` | `run_anomaly_scan()` — L103 |
| Per-metric z-score evaluation | `core/src/risk_monitoring/anomaly_engine.py` | `_evaluate_one()` — L58 |
| Monitored ratio list | `core/src/risk_monitoring/anomaly_engine.py` | `_MONITORED_RATIOS` |

### What the analyst sees — real output (TCS.NS)

```
Risk checks (metrics/risk.py):
  negative_ebitda_check              PASS
  declining_pat_check                PASS
  margin_compression_check           WARN   "Net margin moved from 18.69% to 18.43% (-0.26pp)"
  rising_debt_check                  WARN   "Total debt CAGR = 13.64%"
  weak_dscr_check                    (REQUIRES_ADDITIONAL_DOCUMENT — no debt schedule supplied)

Anomaly scan (anomaly_engine.py) — vs TCS's own 4-year history:
  overall_status: FAIL   {PASS: 0, WARN: 3, FAIL: 2}
  Net Debt / EBITDA        [FAIL]  "0.067 in 2026-FY, 4.72 std-dev above its own historical
                                     mean of 0.00367 (historical range [-0.015, 0.016])"
  Interest Coverage        [FAIL]  "54.6x in 2026-FY, 5.57 std-dev below its own historical
                                     mean of 74.8x (historical range [69.8, 78.3])"
  Debt-to-Equity            [WARN]
  Equity Ratio               [WARN]
  Current Ratio                [WARN]
```

This is a real, useful signal: TCS is a near-zero-net-debt company historically, so even a small
absolute increase in net debt registers as a large *relative* anomaly — exactly the "just broke from
its own pattern" signal continuous monitoring is meant to catch, distinct from the absolute-threshold
view (which still shows the company as healthy overall).

No scheduler/real-time infrastructure was added — this runs on demand (page load / re-analysis),
per the brief's explicit instruction not to over-build.

---

## 7. Credit Intelligence — Working Capital Agent — `src/credit/`

### What it is

Tandon Method II style working-capital assessment. **MPBF is always `ESTIMATED`, Drawing Power is
always `REQUIRES_ADDITIONAL_DOCUMENT`** — never presented as bank-grade (brief section 13).

```python
# working_capital_agent.py — the exact Tandon Method II flow from the brief
wcg = [a - l for a, l in zip(ca, cl)]                     # Working Capital Gap = TCA - CL
min_nwc = [round(a * 0.25, 2) for a in ca]                 # 25% of TCA
estimated_mpbf = [round(g - m, 2) for g, m in zip(wcg, min_nwc)]   # WCG - Min NWC
```

`estimated_drawing_power` is unconditionally `requires_document(...)` — the function has no code
path that produces a numeric value for it, by construction:

```python
facts.append(requires_document(
    metric="estimated_drawing_power", category=CATEGORY,
    reason=("Drawing Power requires bank-specific inventory and receivables margin percentages "
            "from the sanction letter, plus current inventory/receivables ageing ... "
            "It is never estimated from the balance sheet alone."),
))
```

### Where it lives

| What | File | Key symbol |
|---|---|---|
| Tandon Method II computation | `src/credit/working_capital_agent.py` | `compute_working_capital_facts()` — L32 |
| DSO/DIO/DPO helper (shared pattern with `metrics/efficiency.py`) | `src/credit/working_capital_agent.py` | `_days()` — L135 |
| Orchestration + LLM narration | `src/credit/working_capital_agent.py` | `run()` — L160 |

### What the analyst sees — real output (TCS.NS, FY2026)

```
gross_working_capital         = ₹1,357.05bn   [CALCULATED]
working_capital_gap           = ₹747.91bn     [ESTIMATED]
minimum_stipulated_nwc        = ₹339.26bn     [ESTIMATED]   (25% of TCA)
borrower_contribution         = ₹747.91bn     [ESTIMATED]
estimated_mpbf                = ₹408.65bn     [ESTIMATED]
current_asset_coverage_ratio  = 2.228         [CALCULATED]
dso  = 78.78 days   dpo = 19.17 days   operating_cycle = 78.85 days   ccc = 59.68 days
estimated_drawing_power       = REQUIRES_ADDITIONAL_DOCUMENT

LLM narrative (excerpt):
  "... The 'estimated MPBF' figures (e.g., INR 391.445 bn in FY2023, INR 408.648 bn in FY2026)
   are internal estimates and not bank-sanctioned limits, and drawing-power cannot be quantified
   at this stage because the required margin percentages and ageing data are missing (additional
   documentation required)."
```

The LLM volunteered the "not bank-sanctioned" caveat unprompted beyond the system prompt's general
instruction — because the fact it was handed is literally labelled `ESTIMATED`/
`REQUIRES_ADDITIONAL_DOCUMENT` and the prompt tells it to say so explicitly.

---

## 8. Geography-wise Impact Analysis — `src/geography/`

### What it is

Regional revenue/share/growth/volatility are 100% Python-computed from user-entered figures (best-
effort regex extraction from pasted segment-note text is offered as a starting point — Bloomberg PDF
exports don't carry a geographic segment note, so this is not the primary V1 ingestion path).
For any region with a ≥15% YoY swing, recent NewsAPI headlines are shown to the LLM, which **must**
separate its answer into a `FACT:` block (the computed numbers) and a `POSSIBLE EXPLANATION:` block
(hedged language, or an explicit "no headline references this company" caveat).

### Where it lives

| What | File | Key symbol |
|---|---|---|
| Best-effort region/value extraction from pasted text | `src/geography/geography_extractor.py` | `extract_regional_revenue()` |
| Deterministic share/growth/volatility | `src/geography/geography_agent.py` | `compute_regional_metrics()` — L31 |
| Orchestration + LLM narration | `src/geography/geography_agent.py` | `run()` — L77 |
| Notable-swing threshold | `src/geography/geography_agent.py` | `_NOTABLE_SWING_PCT = 15.0` |

### What the analyst sees — real output (illustrative regional split for TCS)

```
North America: FY25 share 46.27% (down from 52.08%), YoY -5.6%    — not notable
Europe:        FY25 share 20.08%, YoY +6.67%                       — not notable
India:         FY25 share 6.59% (up from 6.04%), YoY +15.86%       — NOTABLE SWING

LLM narrative:
  FACT: [table of the exact revenue/share/growth numbers above — Python-computed]

  POSSIBLE EXPLANATION (India — notable swing):
  "The headlines from BusinessLine on 21 Sept 2026 note that 'Sensex rises 564 pts... aided by
   bargain-buying...' and on 18 Sept 2026 that 'Sensex slips but Nifty gains... easing crude
   offers relief.' These market-wide moves could suggest a broader improvement in investor
   sentiment... No headline directly references Tata Consultancy Services or its India
   operations, so the above linkage is speculative and should be viewed only as a possible
   contributing factor."
```

That final sentence is the model correctly following the "clearly frame it as a possible cause, and
say so explicitly if no headlines were available" instruction from the system prompt — it found
generic market headlines, not company-specific ones, and said exactly that rather than overclaiming.

---

## 9. Governance — Executive Background Agent — `src/governance/`

### What it is

DIN/director extraction (best-effort regex over pasted filing text) → statutory registry lookup
(`GovernanceProvider`, `NOT_CONFIGURED` — see §3) → deterministic keyword-based adverse-mention
screen over recent news headlines → LLM narrates, explicitly barred from treating a keyword hit as
proof of anything.

```python
# governance_agent.py — the entire "accusation" logic is a hit-count, not a judgment
_RED_FLAG_KEYWORDS = frozenset({"fraud", "investigation", "disqualified", "insolvency", ...})

def _screen_articles(director_name, articles):
    matches = []
    for art in articles:
        text = f"{art.get('title','')} {art.get('description','')}".lower()
        hits = sorted(k for k in _RED_FLAG_KEYWORDS if k in text)
        if hits:
            matches.append({"title": ..., "matched_keywords": hits})
    return {"director": director_name, "articles_scanned": len(articles), "matches": matches}
```

The system prompt is explicit: *"A keyword match in a news headline is NOT proof of wrongdoing —
always describe matches as 'requires manual verification'... If the statutory registry lookup is
NOT_CONFIGURED, say plainly that statutory records could not be checked, rather than implying a
clean record."*

### Where it lives

| What | File | Key symbol |
|---|---|---|
| Best-effort DIN/name extraction | `src/governance/din_extractor.py` | `extract_directors()` |
| Deterministic keyword screen | `src/governance/governance_agent.py` | `_screen_articles()` — L39 |
| Orchestration + LLM narration | `src/governance/governance_agent.py` | `run()` — L52 |

### What the analyst sees — real output

```
extracted directors: N. Chandrasekaran (DIN 00121863), Rajesh Gopinathan (DIN 07977844)

N. Chandrasekaran  -> PASS         statutory: NOT_CONFIGURED | 2 articles scanned, 0 matches
Rajesh Gopinathan  -> UNAVAILABLE  statutory: NOT_CONFIGURED | 0 articles scanned, 0 matches

LLM narrative:
  "Statutory registry checks could not be performed for either individual because the statutory
   lookup service is not configured, so no statutory record verification is available. The
   adverse-media screen for N. Chandrasekaran covered two articles and returned no matches,
   resulting in a PASS status... While no adverse mentions were found, the inability to verify
   statutory records should be addressed to complete the governance assessment."
```

Governance status is always reported **separately** from financial health — it's never blended into
one combined score (brief section 18: "no-judgment reporting").

---

## 10. UI Integration — `ui/v2_pages.py` + `app.py`

### What it is

Seven new sidebar pages, kept in their own module rather than growing the already-1900-line
`app.py` further: **Financial Metrics, Forecast, Competitive Intelligence, Risk & Alerts, Credit
Intelligence, Geography, Governance**.

| Where | File |
|---|---|
| Import | `app.py` L44 — `from ui import v2_pages` |
| Nav radio options | `app.py` — sidebar radio list, extended with the 7 new labels |
| Routing | `app.py` — `main()`, exact-match `if page == "..."` dispatch (switched from V1's substring match to avoid `"Financial Metrics"` colliding with `"Financial Analysis"`) |
| Page renderers | `core/ui/v2_pages.py` | `page_financial_metrics()`, `page_forecast()`, `page_competitive()`, `page_risk_alerts()`, `page_credit()`, `page_geography()`, `page_governance()` |
| Status badge (CALCULATED/ESTIMATED/.../PASS/WARN/FAIL, colour-coded) | `core/ui/v2_pages.py` | `status_badge()` — L50 |
| Cached Fact Ledger per loaded dataset | `core/ui/v2_pages.py` | `get_or_build_fact_ledger()` — L59, keyed by SHA-256 of `time_series` so it only rebuilds when the data actually changes |
| Network-failure isolation | `core/ui/v2_pages.py` | `_safe_call()` — L73, mirrors V1's `app.py::_safe_run` — an unreachable LLM endpoint surfaces as `st.error`, never crashes the page |

### A UI gotcha worth knowing

`_facts_dataframe()` casts every `Fact.value` to `str` before handing rows to `pd.DataFrame` /
`st.dataframe`. Reason: a single category can mix numeric facts (`revenue = 1500`) with label facts
in the same "Value" column (`revenue_trend_direction = "increasing"`), and a mixed-dtype pandas
column breaks PyArrow serialisation inside Streamlit (`ArrowInvalid: Could not convert 'increasing'
... to double`) — caught and fixed during regression testing (see §13).

---

## 11. Two pre-existing V1 bugs found and fixed while wiring V2 up

Neither of these is a V2 defect — they're old code paths that had never been exercised with a real
API key/model before. Documenting them here so nobody "fixes" them back.

### 11a. Groq's hardcoded default model was dead

`app.py::_provider_defaults("groq")` returned the literal `"llama-3.3-70b-versatile"`, which Groq
has since retired (`404 model_not_found`). Worse: the sidebar's per-rerun "seed defaults from
provider" logic in `main()` would **overwrite** a correct `.env`-supplied `LLM_MODEL` with this dead
literal on every page load, because the overwrite condition checked
`st.session_state["llm_model"] in {"", _DEFAULT_MODEL, ...}` — and since the session was *just*
seeded to `_DEFAULT_MODEL` (the env value), it always matched and got clobbered.

**Fix** (`app.py::_provider_defaults()`, ~L137): when `.env`'s `LLM_PROVIDER` matches the provider
being requested, return the env-derived `_DEFAULT_BASE_URL`/`_DEFAULT_MODEL` instead of the
hardcoded literal. The literal is now only a last-resort fallback when nothing is configured.

```python
_env_matches = _env_provider == provider
if provider == "groq":
    return (
        _DEFAULT_BASE_URL if _env_matches else "https://api.groq.com/openai/v1",
        _DEFAULT_MODEL if _env_matches else "llama-3.3-70b-versatile",
        "Groq API key",
    )
```

Current working default: `LLM_MODEL=openai/gpt-oss-120b` (confirmed live via Groq's `/v1/models`
and a real completion call).

### 11b. FMP supplemental fetch used a retired endpoint

`src/supplemental_fetchers.py::fetch_missing_from_fmp()` called
`https://financialmodelingprep.com/api/v3/balance-sheet-statement/{ticker}` — FMP retired all
`/api/v3/<statement>/<symbol>` path-param endpoints in their August 2025 migration (403 "Legacy
Endpoint"). This silently broke V1's supplemental-data auto-fill and the credibility engine's
yfinance↔FMP dual-source cross-check for any user with a post-migration FMP key.

**Fix**: migrated to `https://financialmodelingprep.com/stable/balance-sheet-statement` with query
params (`symbol=`, `period=`, `limit=`) instead of a path segment. While in there, also mapped the
new response's `inventory` / `accountsReceivables` / `accountPayables` fields (and Alpha Vantage's
equivalents) into the V2 canonical fields, so supplemental fetch now backfills
`inventory`/`accounts_receivable`/`accounts_payable` for the metrics engine too, at no extra cost.

Both fixes were verified against the real, live FMP/Alpha Vantage/Groq keys — not just read for
plausibility.

---

## 12. Regression verification performed

- Every V1 canonical-field regex in `src/mapper.py` still resolves identically (`"Total Revenue"` →
  `revenue`, `"Cost of Goods Sold"` → `cost_of_revenue`, etc.) — spot-checked against the new
  additions to confirm no overlap/shadowing.
- Full `app.py` import + `streamlit.testing.v1.AppTest` pass across **all 12 pages** (5 V1 + 7 V2),
  in both the no-data and loaded-data states, including a live button click against an unreachable
  LLM endpoint (confirms `_safe_call`/`_safe_run` degrade to `st.error`, never a crash).
- Live end-to-end runs (real Groq + yfinance + FMP + Alpha Vantage + NewsAPI) for: metrics engine,
  anomaly scan, assumption validation + forecast, competitive intelligence, working capital, geography,
  governance — all captured in this document as real, unedited output.

---

## Quick Reference — Files Changed / Added

```
NEW — core/metrics/  (Deterministic Financial Metrics Engine, ~1,900 lines)
  ├── __init__.py            public entry point: build_fact_ledger
  ├── schema.py               Fact, FactLedger, status constants
  ├── util.py                  period/series helpers, Fact-list builders
  ├── engine.py                 orchestrates all 12 category modules
  ├── revenue.py  cost.py  profitability.py  liquidity.py  solvency.py
  ├── debt_service.py  efficiency.py  returns.py  cash_flow.py
  └── growth.py  trends.py  risk.py

NEW — core/src/external/   (External Data Layer abstraction)
  ├── base.py                   ExternalDataProvider, ProviderResult
  ├── peer_data_provider.py     live — yfinance + metrics engine
  ├── macro_provider.py          live — World Bank Open Data
  ├── guidance_provider.py        live — user-entered
  ├── news_provider.py             live — wraps sentiment_agent.fetch_news
  ├── analyst_estimates_provider.py  NOT_CONFIGURED
  └── governance_provider.py          NOT_CONFIGURED (MCA/SEBI/IBBI)

NEW — core/src/forecast/       assumption_validation_agent.py, forecast_engine.py
NEW — core/src/competitive/    peer_benchmarking.py, competitive_intelligence_agent.py
NEW — core/src/risk_monitoring/ anomaly_engine.py
NEW — core/src/credit/          working_capital_agent.py
NEW — core/src/geography/       geography_extractor.py, geography_agent.py
NEW — core/src/governance/      din_extractor.py, governance_agent.py

NEW — core/ui/v2_pages.py       7 new dashboard pages

MODIFIED — core/src/mapper.py                  + new canonical field regexes (additive)
MODIFIED — core/src/yfinance_ingestion.py       + cash flow / inventory / AR / AP mapping
MODIFIED — core/src/private_company_ingestion.py + new template columns
MODIFIED — core/src/supplemental_fetchers.py     FMP endpoint fix (§11b) + new field maps
MODIFIED — core/app.py
  ├── import ui.v2_pages
  ├── sidebar nav radio            — 7 new page labels
  ├── main() routing                — switched to exact-match dispatch
  ├── _provider_defaults()           — env-aware Groq/Gemini defaults (§11a)
  └── _delete_session_data()          — clears new V2 session_state keys too

MODIFIED — core/CHANGES.md      V2 changelog entry, same convention as every prior V1 entry
NEW — finveritas/core/.env       LLM_PROVIDER, LLM_MODEL, GROQ_API_KEY, FMP_API_KEY,
                                   ALPHA_VANTAGE_API_KEY, NEWS_API_KEY (gitignored at repo root)
```
