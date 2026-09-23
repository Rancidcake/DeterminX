"""Free-text -> structured regional revenue extraction (LLM-assisted NLU only).

This is NOT a "give me market sense on a hypothetical" engine — the V2 brief
explicitly marks scenario-shock / forward-looking hypothesis reasoning as
EXPERIMENTAL and says not to build it as a core feature (section 25), because
it would mean the LLM reasoning over numbers Python never validated.

What this module actually does: the user types a plain-English description of
*real, already-known* regional performance (e.g. "India revenue was ₹145bn in
FY24 and ₹168bn in FY25, North America was flat around ₹1,200bn both years"),
and the LLM's only job is to transcribe the numbers already present in that
text into structured `{region: {period: value}}` JSON — exactly the same
extraction job `geography_extractor.py` does with regex, just far more
tolerant of natural phrasing. It must never invent, estimate, or infer a
figure that isn't explicitly stated. The extracted data is then run through
the same `compute_regional_metrics()` / `run()` pipeline as every other input
path — this module produces raw extracted data, never an analysis, and the
UI always shows the extraction back to the user for confirmation before it's
used (see `ui/v2_pages.py::page_geography()`).
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

_SYSTEM_PROMPT = (
    "You extract structured data from text describing a company's regional revenue "
    "performance. You are a transcription tool, not an analyst: you only copy out numbers "
    "the user explicitly stated. Do not compute, estimate, infer, round, or invent any "
    "region, period, or value that is not explicitly present in the text. If a value is "
    "described only qualitatively (e.g. 'grew a lot', 'strong quarter') with no number "
    "attached, omit it entirely rather than guessing a figure. "
    "Expand magnitude words/abbreviations into their full absolute number — this is lossless "
    "transcription, not estimation: 'bn'/'billion'/'b' -> x1,000,000,000; 'mn'/'million'/'m' -> "
    "x1,000,000; 'cr'/'crore' -> x10,000,000; 'lakh' -> x100,000; 'k'/'thousand' -> x1,000. "
    "Example: '₹145bn' -> 145000000000. Strip currency symbols/codes; report only the number. "
    "Respond with ONLY a JSON object, no prose, no markdown code fences, in exactly this shape:\n"
    '{"regions": {"<region name>": {"<period>": <number>, ...}, ...}}\n'
    "Period labels must be in 'YYYY-FY' or 'YYYY-QN' form (e.g. 'FY24' -> '2024-FY', "
    "'Q2 2024' -> '2024-Q2'). If no period is stated or implied for a number, omit that "
    "number rather than guessing a period."
)


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    return raw


def parse_scenario_text(
    *, text: str, base_url: str, model: str, api_key: str,
) -> dict[str, Any]:
    """Extract {region: {period: value}} from free text.

    Returns {"regions": {...}, "warnings": [...], "raw_text": text}.
    Never raises for a bad/unparseable model response — returns an empty
    "regions" dict with an explanatory warning instead, exactly like the
    regex-based extractor's "found nothing" path.
    """
    if not text or not text.strip():
        return {"regions": {}, "warnings": ["No text supplied."], "raw_text": text}

    # Generous max_tokens: reasoning-capable models (e.g. Groq's gpt-oss family)
    # spend part of the completion budget on hidden reasoning tokens before the
    # visible JSON, and can otherwise get cut off mid-object (finish_reason="length").
    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0, max_tokens=2000)
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=f"Extract regional revenue data from this text:\n\n{text.strip()}"),
    ]
    resp = llm.invoke(messages)
    raw = _strip_code_fence((getattr(resp, "content", "") or ""))

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Best-effort repair for a truncated-but-otherwise-valid object: close
        # any braces the model left open. If this still doesn't parse, give up
        # and report the raw output rather than guessing at the content.
        repaired = raw + "}" * (raw.count("{") - raw.count("}"))
        try:
            parsed = json.loads(repaired) if repaired != raw else None
            if parsed is None:
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            return {
                "regions": {}, "raw_text": text,
                "warnings": [f"Could not parse a structured response from the model. Raw output: {raw[:300]!r}"],
            }

    regions = parsed.get("regions") if isinstance(parsed, dict) else None
    if not isinstance(regions, dict):
        return {"regions": {}, "raw_text": text, "warnings": ["Model response did not contain a 'regions' object."]}

    clean: dict[str, dict[str, float]] = {}
    warnings: list[str] = []
    for region, periods in regions.items():
        if not isinstance(periods, dict):
            warnings.append(f"Skipped region '{region}': not a period→value mapping.")
            continue
        clean_periods: dict[str, float] = {}
        for period, value in periods.items():
            try:
                clean_periods[str(period)] = float(value)
            except (TypeError, ValueError):
                warnings.append(f"Skipped {region}/{period}: value {value!r} is not numeric.")
        if clean_periods:
            clean[str(region)] = clean_periods

    if not clean:
        warnings.append("No usable region/period/value data could be extracted from the text.")

    return {"regions": clean, "warnings": warnings, "raw_text": text}
