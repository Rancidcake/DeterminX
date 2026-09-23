# Knowledge Transfer — AMD ROCm / vLLM & Shelf Company Filter

**Project:** FinVeritas — Explainable Financial Analysis Platform
**Audience:** Developer or analyst picking up the codebase cold

---

## Part 1 — AMD ROCm / vLLM GPU Integration

### What it is

FinVeritas uses an LLM to narrate pre-computed financial metrics (it never feeds raw documents to the model). By default it points at a local OpenAI-compatible endpoint, but it can now also be aimed at a **vLLM server running on an AMD GPU via ROCm** — no cloud API key required, fully offline inference.

### Where it lives in the code

| What | File | Lines |
|---|---|---|
| Provider defaults function | `core/app.py` | `_provider_defaults()` — L136–167 |
| Provider alias map | `core/app.py` | `_provider_alias` dict — L1764–1774 |
| Provider selectbox | `core/app.py` | L1759–1792 |
| AMD sidebar card (setup instructions) | `core/app.py` | L1816–1831 |
| API key validation bypass | `core/app.py` | `_llm_config_error()` — L115–132 |
| `.env` auto-loader | `core/app.py` | `_load_dotenv_fallback()` — L76–104 |
| Provider-aware key resolver | `core/app.py` | `_env_default_api_key()` — L62–73 |

### How the provider system works

`_provider_defaults(provider)` returns a `(base_url, model, api_key_placeholder)` tuple for each backend. For AMD ROCm:

```python
if provider == "vllm-rocm":
    return (
        "http://localhost:8000/v1",   # vLLM default port
        "Qwen/Qwen2.5-7B-Instruct",  # default model
        "not-needed",                 # no API key required
    )
```

The `"not-needed"` placeholder is recognised by `_llm_config_error()` which returns `None` (no error) for it — so the validation check is bypassed cleanly without a special-case hack.

### Provider alias map

The `.env` file (and `LLM_PROVIDER` environment variable) accepts shorthand strings that all resolve to the same UI label:

```python
"vllm"      → "vLLM (AMD ROCm)"
"vllm-rocm" → "vLLM (AMD ROCm)"
"rocm"      → "vLLM (AMD ROCm)"
```

So `LLM_PROVIDER=rocm` in your `.env` file will auto-select the AMD provider on startup.

### Environment variable configuration

All LLM settings can be pre-configured via a `.env` file in the repo root or workspace root. The loader (`_load_dotenv_fallback`) searches three paths and never overwrites an already-set env var:

```
# .env
LLM_PROVIDER=vllm-rocm
LLM_BASE_URL=http://localhost:8000/v1
LLM_MODEL=Qwen/Qwen2.5-7B-Instruct
LLM_API_KEY=not-needed
```

The `_env_default_api_key(provider)` function selects from three env vars in priority order:

- Groq provider → `GROQ_API_KEY` → `LLM_API_KEY` → fallback
- Gemini provider → `GEMINI_API_KEY` → `LLM_API_KEY` → fallback
- All others → `LLM_API_KEY` → `GEMINI_API_KEY` → `GROQ_API_KEY` → fallback

### What the user sees in the UI

1. Open the sidebar → **LLM Settings** section
2. Select **vLLM (AMD ROCm)** from the provider dropdown
3. Base URL auto-fills to `http://localhost:8000/v1`
4. Model auto-fills to `Qwen/Qwen2.5-7B-Instruct`
5. API key field shows `not-needed` (no input required)
6. An orange info card appears below the API key field:

```
┌─────────────────────────────────────────────────────┐
│ AMD ROCm / vLLM                                     │
│ Start vLLM with ROCm support:                       │
│   HSA_OVERRIDE_GFX_VERSION=11.0.0 \                 │
│   vllm serve Qwen/Qwen2.5-7B-Instruct \             │
│     --dtype float16 --max-model-len 4096            │
│ See requirements-rocm.txt for setup.                │
└─────────────────────────────────────────────────────┘
```

This card only renders when `vLLM (AMD ROCm)` is the active provider — the other providers show their own captions (Gemini and Groq show a short endpoint note; Local/Other show nothing).

### How to actually run vLLM on AMD

**Step 1 — Install ROCm dependencies**

```bash
pip install -r finveritas/core/requirements-rocm.txt
```

**Step 2 — Start the vLLM server**

```bash
HSA_OVERRIDE_GFX_VERSION=11.0.0 \
vllm serve Qwen/Qwen2.5-7B-Instruct \
  --dtype float16 \
  --max-model-len 4096
```

`HSA_OVERRIDE_GFX_VERSION=11.0.0` is required for ROCm to correctly identify the GPU microarchitecture. Adjust the version number to match your card (11.0.0 covers RDNA3 / RX 7000-series).

**Step 3 — Start FinVeritas**

```bash
cd finveritas/core
streamlit run app.py
```

Select **vLLM (AMD ROCm)** in the sidebar. The app will call `http://localhost:8000/v1` for all LLM narration. No internet connection needed.

### Why `_provider_key` not the display label

The internal key (`"vllm-rocm"`) is what gets passed to `_provider_defaults()` and `_env_default_api_key()`. The display label (`"vLLM (AMD ROCm)"`) is only used in the selectbox. This separation lets the alias map translate multiple `.env` values to one display string without touching the defaults logic.

---

## Part 2 — Shelf / Shell Company Filter

### What it is

A dormant entity detection check that runs automatically on every dataset loaded into FinVeritas. Its purpose is to flag companies that appear to exist on paper but have no real operational activity — a common pattern in nominee structures, round-tripping, and layering schemes.

The check is always visible as a dedicated panel on the **Upload Statement** page, immediately after the Data Credibility Score card. It shows regardless of outcome (CLEAR, CAUTION, or HIGH RISK) so analysts cannot miss it.

### Where it lives in the code

| What | File | Lines |
|---|---|---|
| Detection logic | `core/src/data_verifier.py` | `_check_shelf_company_indicators()` — L341–407 |
| Wired into credibility report | `core/src/data_verifier.py` | `run_verification()` — L494 |
| UI panel renderer | `core/app.py` | `_render_shelf_company_panel()` — L249–296 |
| Call site in Upload page | `core/app.py` | L998–1004 |

### The four detection signals

The function collects signals into a list. Each signal that fires adds one entry. The number of signals determines the outcome.

**Signal 1 — Revenue negligible**

```python
if rev_vals and max(abs(v) for v in rev_vals) < 100:
    signals.append("revenue negligible across all periods (< 100 units)")
```

If the largest revenue figure across all periods is below 100 (in whatever unit the dataset uses — millions, thousands, etc.), the company has no meaningful income. Real operating companies will have figures in the thousands or millions.

**Signal 2 — Revenue-to-assets ratio below 2%**

```python
ratio = max_rev / max_assets
if ratio < 0.02:
    signals.append(f"revenue/assets ratio {ratio:.2%} (below 2%)")
elif ratio < 0.05:
    signals.append(f"low revenue/assets ratio {ratio:.1%}")
```

A real operating business uses its assets to generate revenue. A ratio below 2% means the entity holds assets (cash, property, investments) but generates almost no income from them — a classic shelf company profile. The 2–5% band triggers a softer WARN-only signal.

**Signal 3 — Near-zero liabilities relative to assets**

```python
if max_assets > 0 and max_liab / max_assets < 0.05:
    signals.append(f"near-zero liabilities vs assets ({max_liab / max_assets:.1%})")
```

Operating companies always carry liabilities — trade payables, accrued expenses, debt. A company with significant assets but almost no liabilities (< 5% of assets) has no suppliers, no borrowings, and no operational obligations. That is not how a real business looks.

**Signal 4 — Dormant financials**

```python
for fname, entries in ts.items():
    ...
    if changes and max(changes) < 0.01:
        dormant_fields.append(fname)
if len(dormant_fields) >= 3:
    signals.append(f"static financials on {len(dormant_fields)} fields (< 1% YoY change)")
```

For each time series field, the function computes the maximum year-over-year percentage change. If that maximum is below 1% (i.e., the field barely moves across all periods), the field is marked dormant. If 3 or more fields are dormant simultaneously, the company's overall financial profile is static — consistent with a company that exists but does nothing.

### Outcome logic

```python
if not signals:        → STATUS_PASS   (green — CLEAR)
elif len(signals) >= 2 → STATUS_FAIL   (red   — HIGH RISK)
else:                  → STATUS_WARN   (amber — CAUTION)
```

One signal alone is not conclusive — some legitimate niche businesses have low revenue/asset ratios. Two or more signals together is a strong combined indicator.

The check is registered with **weight 15** in the credibility report, meaning it contributes up to 15 points out of 100 to the overall credibility score. A FAIL on this check deducts those 15 points.

### What the analyst sees

The panel renders as a section header + card directly below the credibility score, always expanded:

**CLEAR (green)**
```
✅  CLEAR
No dormant / shell company indicators detected
No dormant or shell company signals detected in the available financial data.
```

**CAUTION (amber)**
```
⚠️  CAUTION
Possible shelf company indicator — revenue/assets ratio 1.2% (below 2%)
At least one shelf/shell company indicator detected. Verify operational activity,
beneficial ownership, and business purpose before proceeding.
```

**HIGH RISK (red)**
```
🚫  HIGH RISK
Multiple shelf/shell company signals — revenue/assets ratio 0.3% (below 2%);
near-zero liabilities vs assets (0.8%); static financials on 4 fields (< 1% YoY change).
Manual review required.
Multiple signals indicate this entity may be a dormant or shell company. Nominee
ownership, round-tripping, and layering are common risk vectors. Enhanced due
diligence required before any credit or investment decision.
```

### How it fits into the credibility pipeline

```
run_verification(source, payload, ...)
    └── _check_completeness()
    └── _check_temporal_coverage()
    └── _check_accounting_identity()
    └── _check_freshness()
    └── _check_yoy_plausibility()
    └── _check_internal_consistency()
    └── _check_shelf_company_indicators()   ← always last
        └── returns CredibilityCheck(name="Shelf Company Indicators", status=..., weight=15)

→ CredibilityReport.checks contains all of the above
→ report.score = weighted average of non-skipped checks
```

After `run_verification()` returns in `page_upload()`:

```python
_shelf_check = next(
    (c for c in _report.checks if c.name == "Shelf Company Indicators"), None
)
if _shelf_check:
    _render_shelf_company_panel(_shelf_check)
```

The check is always present (never skipped) so `_shelf_check` will always be found and the panel always renders.

### Risk context — why these signals matter

| Signal | Risk it points to |
|---|---|
| Near-zero revenue | Nominee / dormant incorporation — entity created but never operated |
| Low revenue/assets ratio | Pass-through structure — assets held but not deployed for business |
| Near-zero liabilities | No suppliers, no staff, no debt — no real business activity |
| Static financials | Round-tripping — same numbers recycled across reporting periods |

These patterns appear frequently in shell company abuse for layering (money laundering stage 2), invoice fraud, and beneficial ownership concealment. The filter does not make a legal determination — it surfaces signals for human analysts to investigate before any credit or investment decision is made.

---

## Quick Reference — Files Changed

```
finveritas/core/app.py
  ├── import html                              (line 13)
  ├── _env_default_api_key()                   (line 62)
  ├── _load_dotenv_fallback()                  (line 76)
  ├── _llm_config_error()  — not-needed bypass (line 129)
  ├── _provider_defaults() — vllm-rocm case   (line 151)
  ├── _render_shelf_company_panel()            (line 249)
  ├── _provider_alias map  — vllm aliases     (line 1764)
  ├── Provider selectbox   — vLLM option      (line 1759)
  └── AMD sidebar card     — HSA command      (line 1816)

finveritas/core/src/data_verifier.py
  ├── _check_shelf_company_indicators()        (line 341)
  └── run_verification()   — shelf check call (line 494)
```
