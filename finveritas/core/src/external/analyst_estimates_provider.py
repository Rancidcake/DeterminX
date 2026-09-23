"""Analyst Estimates Provider.

No analyst-consensus data source (e.g. Refinitiv/I-B-E-S, Visible Alpha,
Bloomberg consensus estimates) is wired into this deployment — those are
paid, credentialed feeds. Per section 17/22 of the V2 brief: a source that
cannot be reliably queried must say so, not synthesize a plausible-looking
number. This adapter exists so the Assumption Validation Agent has a stable
interface to call; swapping in a real feed later requires no change to the
agents that consume it.
"""

from __future__ import annotations

from src.external.base import ExternalDataProvider, ProviderResult, not_configured

PROVIDER_NAME = "analyst_estimates"
SOURCE_TYPE = "analyst_estimates"


class AnalystEstimatesProvider(ExternalDataProvider):
    name = PROVIDER_NAME
    source_type = SOURCE_TYPE

    def fetch(self, *, entity: str, metric: str = "revenue_growth") -> ProviderResult:
        return not_configured(
            self.name, self.source_type,
            "No analyst-consensus estimates provider is configured for this deployment "
            "(requires a licensed feed such as I/B/E/S, Visible Alpha, or a Bloomberg terminal "
            "entitlement). Analyst estimates are excluded from assumption validation until one "
            "is connected.",
        )
