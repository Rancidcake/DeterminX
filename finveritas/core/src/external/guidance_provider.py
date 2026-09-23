"""Management Guidance / Earnings-Call Provider.

Accepts USER-SUPPLIED guidance (typed into the Forecast UI, e.g. "management
guided 8-10% revenue growth for FY26") — FinVeritas does not scrape or
transcribe earnings calls. Treating this as an explicit provider (rather than
a free-text field the forecast engine reads directly) keeps the same
source/status/timestamp contract as every other external fact, and keeps the
door open for a real transcript-ingestion connector later without changing
the Assumption Validation Agent's interface.
"""

from __future__ import annotations

from src.external.base import ExternalDataProvider, ProviderResult, ok, unavailable

PROVIDER_NAME = "management_guidance"
SOURCE_TYPE = "management_guidance"


class GuidanceProvider(ExternalDataProvider):
    name = PROVIDER_NAME
    source_type = SOURCE_TYPE

    def fetch(
        self, *, low: float | None = None, high: float | None = None,
        note: str = "",
    ) -> ProviderResult:
        if low is None and high is None:
            return unavailable(
                self.name, self.source_type,
                "No management guidance was entered. FinVeritas does not auto-extract guidance "
                "from earnings-call transcripts in this deployment; enter a disclosed range manually "
                "if the company has published one.",
            )
        return ok(self.name, self.source_type,
                   {"low": low, "high": high, "note": note},
                   raw_reference="user-entered management guidance")
