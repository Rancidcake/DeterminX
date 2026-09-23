# FinVeritas — Explainable Financial Analysis Platform

Bloomberg Terminal-style financial risk analysis system. Ingests structured financial data from multiple sources, runs a deterministic multi-agent pipeline, and produces explainable outputs with a full audit trail.

---

## Changelog

All notable changes are documented here in reverse chronological order.

---

### Shelf / Shell Company Filter *(latest)*

**Files:** `core/src/data_verifier.py`, `core/app.py`

Added a dedicated shelf company detection check that runs automatically on every ingested dataset and renders as a permanent, always-visible panel on the Upload page — not buried in the credibility expander.

**Four detection signals:**
- Revenue negligible — all revenue values < 100 units across all periods
- Revenue-to-assets ratio < 2% — no meaningful operational activity relative to asset base
- Near-zero liabilities vs assets — real operating businesses carry payables/debt (< 5% flags)
- Dormant financials — ≥ 3 fields with < 1% year-over-year change across all periods

**Three outcome states:**
- ✅ CLEAR (green) — no indicators detected
- ⚠️ CAUTION (amber) — one signal; verify operational activity and beneficial ownership
- 🚫 HIGH RISK (red) — two or more signals; possible shell/nominee entity, enhanced due diligence required

The check is wired into the `CredibilityReport` as a universal check (weight 15) so it also appears in the detailed credibility breakdown.

---

### AMD ROCm / vLLM GPU Integration

**Files:** `core/app.py`

Added **vLLM (AMD ROCm)** as a selectable LLM provider in the sidebar. Enables running open-weight models locally on AMD GPUs using ROCm without any cloud API dependency.

**What was added:**
- New provider option `vLLM (AMD ROCm)` in the provider selectbox
- Default endpoint set to `http://localhost:8000/v1` (standard vLLM port)
- Default model set to `Qwen/Qwen2.5-7B-Instruct`
- API key automatically set to `not-needed` (vLLM local requires no key)
- In-sidebar setup instructions showing the exact launch command:
  ```
  HSA_OVERRIDE_GFX_VERSION=11.0.0 \
  vllm serve Qwen/Qwen2.5-7B-Instruct \
    --dtype float16 --max-model-len 4096
  ```
- `not-needed` key bypasses the API key validation check so no false config errors appear
- Provider alias map extended: `vllm`, `vllm-rocm`, `rocm` all resolve to the AMD ROCm provider

---

### Multi-Provider LLM Support

**Files:** `core/app.py`

Expanded the LLM backend from a single hardcoded local endpoint to a full provider selector covering five backends:

| Provider | Endpoint | Default Model |
|---|---|---|
| Local / OpenAI-compatible | `http://127.0.0.1:1234/v1` | `qwen2.5-coder-1.5b-instruct-mlx` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| vLLM (AMD ROCm) | `http://localhost:8000/v1` | `Qwen/Qwen2.5-7B-Instruct` |
| Other OpenAI-compatible | configurable | configurable |

**API key validation** added per provider:
- Gemini keys must start with `AIza`
- Groq keys must start with `gsk_`
- Missing or placeholder keys are caught before the pipeline runs

---

### Improved LLM Environment Handling

**Files:** `core/app.py`

**`.env` auto-loader** (`_load_dotenv_fallback`): Searches three candidate paths (`cwd/.env`, repo root, workspace root) and loads `KEY=VALUE` pairs into `os.environ` without overwriting already-set variables. No `python-dotenv` dependency required.

**Provider-aware key resolution** (`_env_default_api_key`): Reads from `LLM_API_KEY`, `GEMINI_API_KEY`, and `GROQ_API_KEY` environment variables and selects the right one based on the active provider. Falls back gracefully across all three.

**All LLM config now overridable via `.env`:**
```
LLM_PROVIDER=groq
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.3-70b-versatile
LLM_API_KEY=gsk_...
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AIza...
NEWS_API_KEY=...
FMP_API_KEY=...
ALPHA_VANTAGE_API_KEY=...
```

**"Reload LLM defaults from .env"** button in sidebar re-applies env values without a full page restart.

---

### Debug News Agent

**Files:** `core/src/debug_news_agent.py`

Standalone diagnostic tool for testing the NewsAPI connection and sentiment pipeline without running the full agent pipeline. Useful for validating API keys and checking what headlines are returned for a given company before a full analysis run.

---

### Data Credibility Score

**Files:** `core/src/data_verifier.py`, `core/app.py`

Automated weighted credibility scoring (0–100) runs on every ingested dataset before the agent pipeline. Confidence levels: HIGH (≥ 80), MEDIUM (≥ 55), LOW (< 55).

**Universal checks (all sources):**
- Field Completeness — how many of 10 key financial fields are present (weight 15)
- Temporal Coverage — number of periods available for trend analysis (weight 10)
- Accounting Identity — Assets = Liabilities + Equity verified per period within 5% (weight 20)
- Data Freshness — flags data older than 18 months (weight 10)
- YoY Plausibility — flags > 500% year-over-year swings as likely unit mismatches (weight 10)
- Internal Consistency — gross profit ≤ revenue, current ≤ total assets/liabilities (weight 15)
- **Shelf Company Indicators** — dormancy and revenue/asset ratio checks (weight 15) ← new

**Source-specific checks:**
- Bloomberg PDF: Bloomberg copyright/legal notice detection in OCR text (weight 25)
- Ticker: active listing confirmation + optional yfinance vs FMP dual-source cross-check (weight 10 + 20)
- CSV/Private: flags that no external reference is available for cross-verification (weight 5)

---

### Supplemental Data Fetching

**Files:** `core/src/supplemental_fetchers.py`, `core/app.py`

When required fields are missing for the Liquidity or Balance Sheet agents, the app offers two resolution paths:

- **Auto-fetch via FMP** (Financial Modeling Prep, 250 req/day free): fetches missing balance sheet fields for the active ticker
- **Auto-fetch via Alpha Vantage** (25 req/day free): backup source

Both pre-fill the manual entry form. The user can edit values before applying. Applied supplemental data is patched into the payload and re-written to disk without re-running OCR.

---

### Account Aggregator (AA) / RBI Consented Data Tab

**Files:** `core/src/aa_ingestion.py`, `core/app.py`

Fourth ingestion tab implementing the RBI Account Aggregator framework. Accepts decrypted FI data in the ReBIT DEPOSIT schema (the format AA providers deliver after user consent). Bank credits are aggregated per quarter as a revenue proxy and fed into the same agent pipeline as other sources.

Includes a sample JSON download for testing. Production AA integration requires FIU registration with RBI; this implementation accepts the decrypted payload for research and POC use.

---

### Meta-Orchestrator Agent

**Files:** `core/src/meta_agent.py`

Self-aware confidence scoring layer that runs after all five primary agents complete. Assesses:
- Per-agent confidence scores (0–100 each)
- Overall confidence label (HIGH / MEDIUM / LOW)
- Drift alerts — flags when agent outputs conflict with each other
- Guardrail audit — checks that no agent produced a credit decision statement
- Optional LLM advisory narrative summarising the combined picture

Output rendered as a dedicated panel on the Financial Analysis page, above the individual agent cards.

---

### Cross Reference Agent

**Files:** `core/agents/cross_reference_agent.py`

LLM-powered synthesis agent that runs after Revenue, Liquidity, Balance Sheet, and Sentiment agents all succeed. Produces an integrated explainable narrative bridging quantitative metrics with qualitative risk language. Displays a summary of the most representative metric from each sub-agent alongside the full narrative.

Skipped automatically if any upstream agent fails (with a clear reason shown in the UI).

---

### Compliance & Audit Trail Page

**Files:** `core/src/audit_log.py`, `core/src/db.py`, `core/app.py`

**SQLite store** (`output/finveritas.db`): Every analysis run, agent execution, and LLM call (prompt + response) is logged to a queryable SQLite database. Viewable in DB Browser for SQLite.

**Tamper-evident JSONL chain** (`output/audit_log.jsonl`): SHA-256 chained audit log. Any modification to a past entry breaks `verify_chain()`. Downloadable from the UI.

**DPDP Act 2023 compliance features:**
- Consent gate on first load — timestamps stored; nothing runs without explicit consent
- Right to erasure — "Delete All Data" button removes all output files and wipes session state
- Data localisation — all output written to `output/` on the local device only; no cloud uploads except to the configured LLM endpoint (which receives metric summaries, not source documents)

---

### Agent Pipeline — Five Primary Agents

**Files:** `core/agents/`, `core/src/`

| Agent | Input | Key Metrics |
|---|---|---|
| Revenue Agent | Income statement time series | CAGR, YoY growth, revenue trend |
| Liquidity Agent | Balance sheet + working capital | Current ratio, quick ratio, liquidity risk flag |
| Balance Sheet Agent | Assets / liabilities / equity | Debt-to-equity, leverage ratio, balance sheet risk |
| Sentiment Agent | Company name + NewsAPI headlines | Dominant sentiment, article count, sentiment score |
| Cross Reference Agent | All four agent outputs | Integrated risk narrative |

All numeric computations are deterministic Python. The LLM is invoked only to narrate pre-computed metrics, ensuring full auditability and no hallucinated numbers.

---

### Data Ingestion — Three Primary Sources

**Files:** `core/ocr/pdf_parser.py`, `core/src/yfinance_ingestion.py`, `core/src/private_company_ingestion.py`

| Tab | Source | Notes |
|---|---|---|
| Bloomberg PDF | OCR via pdfplumber | Supports multi-PDF merge (IS + BS together) |
| Fetch by Ticker | yfinance | Annual statements; examples: `INFY.NS`, `TCS.NS`, `AAPL` |
| Private Company CSV/Excel | User upload | Template download available; columns map to internal schema |
| AA / RBI Consented | ReBIT DEPOSIT JSON | Quarter-aggregated credits as revenue proxy |

All sources normalise to the same internal JSON schema (`entity` + `time_series`) before reaching the agents.

---

### Basel III Alignment Page

**Files:** `core/app.py`

Regulatory context panel documenting how each agent output maps to Basel III Pillar 2 (supervisory monitoring) and Pillar 3 (market discipline) requirements. Includes a clear scope disclaimer: the system does not compute regulatory capital ratios, LCR, NSFR, or any binding prudential measure.

---

### Dev Container

**Files:** `.devcontainer/devcontainer.json`

VS Code / GitHub Codespaces dev container configuration for one-click reproducible environment setup.

---

## Running the App

```bash
cd finveritas/core
pip install -r requirements.txt
streamlit run app.py
```

Open `http://localhost:8501`. Accept the DPDP consent gate, configure your LLM provider in the sidebar, then upload data or fetch by ticker.

**For AMD ROCm GPU inference:**
```bash
pip install -r requirements-rocm.txt
HSA_OVERRIDE_GFX_VERSION=11.0.0 \
vllm serve Qwen/Qwen2.5-7B-Instruct \
  --dtype float16 --max-model-len 4096
```
Then select **vLLM (AMD ROCm)** in the sidebar provider dropdown.
