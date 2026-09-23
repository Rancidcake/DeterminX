"""Macroeconomic Indicator Provider — World Bank Open Data (free, no API key).

Used as one of the reference points for the Assumption Validation Agent
(section 5/22: "relevant macroeconomic indicators where available"). This is
a real network call to a public API, not a stub — but it degrades to
UNAVAILABLE/ERROR cleanly (no key required, but the endpoint can still be
unreachable in an offline/sandboxed environment) rather than ever inventing a
growth figure.
"""

from __future__ import annotations

from typing import Any

import requests

from src.external.base import ExternalDataProvider, ProviderResult, error, ok, unavailable

PROVIDER_NAME = "world_bank"
SOURCE_TYPE = "macro_indicator"

_WORLD_BANK_URL = "https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"

# NY.GDP.MKTP.KD.ZG = GDP growth (annual %)
INDICATOR_GDP_GROWTH = "NY.GDP.MKTP.KD.ZG"
# FP.CPI.TOTL.ZG = Inflation, consumer prices (annual %)
INDICATOR_INFLATION = "FP.CPI.TOTL.ZG"


class MacroProvider(ExternalDataProvider):
    name = PROVIDER_NAME
    source_type = SOURCE_TYPE
    timeout_seconds = 6.0

    def fetch(
        self, *, country_code: str, indicator: str = INDICATOR_GDP_GROWTH,
    ) -> ProviderResult:
        return self._guard(lambda: self._fetch(country_code, indicator))

    def _fetch(self, country_code: str, indicator: str) -> ProviderResult:
        code = (country_code or "").strip().upper()
        if not code:
            return unavailable(self.name, self.source_type, "No country code supplied.")

        url = _WORLD_BANK_URL.format(country=code, indicator=indicator)
        try:
            resp = requests.get(
                url, params={"format": "json", "per_page": 6, "mrnev": 3},
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            return error(self.name, self.source_type, f"World Bank API request failed: {exc}")

        if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
            return unavailable(self.name, self.source_type,
                                f"No data returned for country '{code}' / indicator '{indicator}'.")

        series: list[dict[str, Any]] = [
            {"year": row.get("date"), "value": row.get("value")}
            for row in payload[1] if row.get("value") is not None
        ]
        if not series:
            return unavailable(self.name, self.source_type,
                                f"World Bank has no non-null observations for '{code}' / '{indicator}'.")

        latest = series[0]
        return ok(
            self.name, self.source_type,
            {"country": code, "indicator": indicator, "latest_year": latest["year"],
             "latest_value_pct": latest["value"], "series": series},
            raw_reference=url,
        )
