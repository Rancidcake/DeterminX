"""Best-effort regional-revenue extraction from raw OCR text.

Bloomberg Terminal statement exports (V1's primary PDF source) generally do
NOT carry a geographic segment note — that disclosure lives in the annual
report's segment-reporting footnote. This extractor does a best-effort
regex scan of whatever OCR text is available and returns what it finds;
callers should treat the result as a starting point for user confirmation,
not an authoritative source, and the UI always offers manual entry as the
primary path (see `src/geography/geography_agent.py`).
"""

from __future__ import annotations

import re
from typing import Any

_REGIONS = [
    "North America", "United States", "Europe", "Asia Pacific", "APAC",
    "India", "China", "Japan", "Latin America", "Middle East", "Africa",
    "Rest of World", "Domestic", "International",
]

_NUMBER_RE = r"[\$₹€£]?\s?([\d,]+(?:\.\d+)?)"

# "<Region> ... <number>" on the same line, tolerating a currency symbol and
# thousands separators.
_LINE_PATTERNS = [
    re.compile(rf"^\s*{re.escape(region)}\D{{0,20}}{_NUMBER_RE}", re.IGNORECASE)
    for region in _REGIONS
]


def extract_regional_revenue(text: str, period: str) -> dict[str, float]:
    """Best-effort {region: value} for one period from raw OCR/segment-note text.

    Returns an empty dict (never raises) when nothing recognisable is found —
    callers must fall back to manual entry.
    """
    if not text:
        return {}

    found: dict[str, float] = {}
    for region, pattern in zip(_REGIONS, _LINE_PATTERNS):
        for line in text.splitlines():
            m = pattern.match(line)
            if m:
                raw = m.group(1).replace(",", "")
                try:
                    found[region] = float(raw)
                except ValueError:
                    continue
                break  # first match per region wins

    return found


def merge_regional_series(per_period: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """{period: {region: value}} -> {region: {period: value}}."""
    out: dict[str, dict[str, float]] = {}
    for period, region_vals in per_period.items():
        for region, val in region_vals.items():
            out.setdefault(region, {})[period] = val
    return out
