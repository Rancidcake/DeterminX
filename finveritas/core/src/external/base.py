"""External Data Layer — abstraction (section 22 of the V2 brief).

Every capability that needs data FinVeritas does not itself compute (peer
financials, analyst estimates, management guidance, macro indicators,
governance/statutory records, news) goes through a `ExternalDataProvider`
subclass and gets back a `ProviderResult`, never a raw, untyped payload.

Design rules:
  - A provider that cannot reliably answer MUST return
    `ProviderResult(status="UNAVAILABLE", ...)`, never a fabricated value.
  - Every result carries source, source_type, retrieved_at, so the UI/audit
    trail can show exactly where a number came from (section 24: source
    traceability) — this is what lets the app distinguish a financial fact
    from an external fact from an AI interpretation.
  - Business logic (forecast/competitive/governance agents) must depend only
    on this interface, never on a specific vendor SDK/API directly, so a
    provider can be swapped without touching the agents that consume it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

STATUS_OK = "OK"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_ERROR = "ERROR"
STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    source_type: str
    status: str  # OK / UNAVAILABLE / ERROR / NOT_CONFIGURED
    data: Any = None
    reason: str | None = None
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw_reference: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "source_type": self.source_type,
            "status": self.status,
            "data": self.data,
            "reason": self.reason,
            "retrieved_at": self.retrieved_at,
            "raw_reference": self.raw_reference,
        }


def unavailable(provider: str, source_type: str, reason: str) -> ProviderResult:
    return ProviderResult(provider=provider, source_type=source_type, status=STATUS_UNAVAILABLE, reason=reason)


def not_configured(provider: str, source_type: str, reason: str = "No API key/credentials configured.") -> ProviderResult:
    return ProviderResult(provider=provider, source_type=source_type, status=STATUS_NOT_CONFIGURED, reason=reason)


def error(provider: str, source_type: str, reason: str) -> ProviderResult:
    return ProviderResult(provider=provider, source_type=source_type, status=STATUS_ERROR, reason=reason)


def ok(provider: str, source_type: str, data: Any, raw_reference: str | None = None) -> ProviderResult:
    return ProviderResult(provider=provider, source_type=source_type, status=STATUS_OK, data=data, raw_reference=raw_reference)


class ExternalDataProvider(ABC):
    """Base class every provider adapter implements.

    `name` and `source_type` are fixed metadata; `fetch(**kwargs)` does the
    actual (possibly network) call and must catch its own exceptions —
    callers should never need a try/except around a provider call.
    """

    name: str = "unnamed_provider"
    source_type: str = "unknown"
    timeout_seconds: float = 8.0

    @abstractmethod
    def fetch(self, **kwargs: Any) -> ProviderResult:
        raise NotImplementedError

    def _guard(self, fn, *, source_type: str | None = None) -> ProviderResult:
        """Run `fn()` and translate any exception into an ERROR result instead
        of letting it propagate into the calling agent."""
        try:
            return fn()
        except Exception as exc:  # network/library errors of any shape
            return error(self.name, source_type or self.source_type, str(exc))
