"""News / Event Provider — wraps the existing NewsAPI integration.

V1 already ships a NewsAPI client (`src/sentiment_agent.py::fetch_news`) used
by the Sentiment Agent. Section 15/16 of the V2 brief reuses the same feed
for the Geography Agent's regional-incident correlation, and the Governance
Agent uses it for a lightweight, deterministic "adverse mention" scan of
recent headlines. We call the existing function rather than re-implementing
an HTTP client, per the "reuse existing APIs/utilities" directive.
"""

from __future__ import annotations

import re

from src.external.base import ExternalDataProvider, ProviderResult, error, ok, unavailable

PROVIDER_NAME = "newsapi"
SOURCE_TYPE = "news"

# Trailing legal-entity suffixes to strip before building a NewsAPI query.
# NewsAPI's /v2/everything ANDs unquoted terms together, and real coverage
# almost never writes the full registered name (e.g. "Tata Consultancy
# Services Limited") verbatim — it says "Tata Consultancy Services" or "TCS".
# Requiring the suffix in every query silently starves the search of real
# hits (confirmed: dropping "Limited" turned 0 results into 5 real articles
# for the same person + company).
_LEGAL_SUFFIX_RE = re.compile(
    r"\s+(?:limited|ltd\.?|inc\.?|incorporated|corp\.?|corporation|plc|llc|"
    r"pvt\.?\s*ltd\.?|private\s+limited|co\.?|company)\s*$",
    re.IGNORECASE,
)


def company_search_name(entity: str) -> str:
    """Strip a trailing legal-entity suffix for use in a free-text news query.

    "Tata Consultancy Services Limited" -> "Tata Consultancy Services"
    "Apple Inc."                        -> "Apple"
    Leaves the name unchanged if no recognised suffix is present.
    """
    return _LEGAL_SUFFIX_RE.sub("", (entity or "").strip()).strip() or entity


class NewsProvider(ExternalDataProvider):
    name = PROVIDER_NAME
    source_type = SOURCE_TYPE

    def fetch(self, *, query: str, api_key: str, max_articles: int = 20) -> ProviderResult:
        return self._guard(lambda: self._fetch(query, api_key, max_articles))

    def _fetch(self, query: str, api_key: str, max_articles: int) -> ProviderResult:
        if not api_key or not api_key.strip():
            return unavailable(self.name, self.source_type,
                                "No NewsAPI key configured (set it in the sidebar).")
        from src.sentiment_agent import fetch_news

        try:
            articles = fetch_news(query, api_key, max_articles=max_articles)
        except Exception as exc:
            return error(self.name, self.source_type, f"NewsAPI request failed: {exc}")

        if not articles:
            return unavailable(self.name, self.source_type, f"No recent articles found for '{query}'.")

        return ok(self.name, self.source_type, {"articles": articles, "query": query},
                   raw_reference="https://newsapi.org/v2/everything")
