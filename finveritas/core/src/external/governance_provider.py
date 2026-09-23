"""Governance / Statutory Records Provider — MCA / SEBI / IBBI (abstraction only).

The Ministry of Corporate Affairs (MCA21), SEBI, and IBBI do not expose a
public, keyless, ToS-compliant bulk API for director/company statutory
lookups — real integration requires a registered/paid data-partner feed or
manual portal lookups. Per section 17 of the V2 brief:

    "Build external-data connectors behind an abstraction/interface.
     Do not hard-code the application around one scraping implementation.
     If a source cannot reliably be queried, show 'Data unavailable'
     rather than generating a result."

This module is exactly that abstraction: a stable interface the Governance
Agent calls, returning NOT_CONFIGURED today. Wiring in a real MCA/SEBI/IBBI
data partner later means implementing `fetch()` here — no change needed in
`src/governance/governance_agent.py`.
"""

from __future__ import annotations

from src.external.base import ExternalDataProvider, ProviderResult, not_configured

PROVIDER_NAME = "governance_registry"
SOURCE_TYPE = "statutory_registry"

REGISTRIES = ("MCA", "SEBI", "IBBI")


class GovernanceProvider(ExternalDataProvider):
    name = PROVIDER_NAME
    source_type = SOURCE_TYPE

    def fetch(self, *, din: str | None = None, director_name: str | None = None) -> ProviderResult:
        subject = din or director_name or "unspecified director"
        return not_configured(
            self.name, self.source_type,
            f"No MCA/SEBI/IBBI data-partner connector is configured for this deployment. "
            f"Cannot look up statutory records for '{subject}'. Wire a licensed registry feed into "
            f"src/external/governance_provider.py to enable this check.",
        )
