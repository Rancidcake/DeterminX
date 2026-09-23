"""Governance Agent (section 17-18 of the V2 brief).

    Extract DIN -> statutory lookup (MCA/SEBI/IBBI, behind an abstraction)
    -> deterministic adverse-mention screen (news keyword match)
    -> governance findings -> LLM narrates alongside financial credibility

No unsupported governance accusation is generated: the keyword screen only
ever reports "N recent articles matched keyword X for <director>", which the
LLM must present as "requires manual verification", never as a proven
finding. The statutory-registry lookup is NOT_CONFIGURED in this deployment
(see `src/external/governance_provider.py`) and is reported as such rather
than silently skipped.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src import db as _db
from src.external.governance_provider import GovernanceProvider
from src.external.news_provider import NewsProvider, company_search_name

# Deterministic keyword screen — a MATCH is a fact ("N articles contain this
# term near the director's name"), never itself an accusation.
_RED_FLAG_KEYWORDS: frozenset[str] = frozenset({
    "fraud", "fraudulent", "investigation", "investigated", "disqualified",
    "disqualification", "insolvency", "ibbi", "sebi action", "sebi order",
    "banned", "debarred", "resign", "resigned", "resignation", "lawsuit",
    "charge-sheeted", "chargesheet", "arrested", "conviction", "convicted",
    "penalty", "penalised", "penalized", "default", "willful defaulter",
    "shell company", "money laundering", "embezzlement",
})


def _screen_articles(director_name: str, articles: list[dict[str, Any]]) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for art in articles:
        text = f"{art.get('title', '')} {art.get('description', '')}".lower()
        hits = sorted(k for k in _RED_FLAG_KEYWORDS if k in text)
        if hits:
            matches.append({
                "title": art.get("title"), "url": art.get("url"),
                "publishedAt": art.get("publishedAt"), "matched_keywords": hits,
            })
    return {"director": director_name, "articles_scanned": len(articles), "matches": matches}


def run(
    *,
    entity: str,
    directors: list[dict[str, str]],
    news_api_key: str = "",
    base_url: str, model: str, api_key: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    if not directors:
        return {
            "entity": entity, "status": "UNAVAILABLE",
            "reason": "No directors/DINs were supplied. Extract them from a filing or enter manually.",
        }

    governance_provider = GovernanceProvider()
    news_provider = NewsProvider()

    findings: list[dict[str, Any]] = []
    for d in directors:
        name = (d.get("name") or "").strip()
        din = (d.get("din") or "").strip() or None

        statutory = governance_provider.fetch(din=din, director_name=name or None)

        screen = {"director": name, "articles_scanned": 0, "matches": []}
        if name and news_api_key.strip():
            news_result = news_provider.fetch(
                query=f'"{name}" {company_search_name(entity)}', api_key=news_api_key, max_articles=10,
            )
            if news_result.ok:
                screen = _screen_articles(name, news_result.data["articles"])

        finding_status = "WARN" if screen["matches"] else ("PASS" if screen["articles_scanned"] else "UNAVAILABLE")

        findings.append({
            "name": name or "(name not extracted)",
            "din": din or "(DIN not extracted)",
            "statutory_lookup": statutory.to_dict(),
            "adverse_mention_screen": screen,
            "status": finding_status,
        })

    system = (
        "You are compiling a governance findings summary. Use ONLY the provided findings — do not invent, "
        "assume, or imply anything not present in the data. A keyword match in a news headline is NOT proof "
        "of wrongdoing — always describe matches as 'requires manual verification', never as an established "
        "fact about the individual. If the statutory registry lookup is NOT_CONFIGURED, say plainly that "
        "statutory records could not be checked, rather than implying a clean record. "
        "Keep this SEPARATE from any financial-health assessment. Write 4-8 concise, professional sentences."
    )
    human = {
        "task": "Summarise governance findings for these directors using ONLY the provided data.",
        "entity": entity,
        "findings": findings,
    }

    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0)
    messages = [SystemMessage(content=system), HumanMessage(content=json.dumps(human, indent=2, default=str))]
    resp = _db.instrumented_invoke(
        llm, messages, run_id=run_id, agent_name="governance_agent", model=model, base_url=base_url,
    )
    narrative = (getattr(resp, "content", "") or "").strip() or "(No narrative generated.)"

    overall = "WARN" if any(f["status"] == "WARN" for f in findings) else (
        "UNAVAILABLE" if all(f["status"] == "UNAVAILABLE" for f in findings) else "PASS"
    )

    return {
        "entity": entity,
        "status": "OK",
        "overall_governance_status": overall,
        "findings": findings,
        "narrative": narrative,
    }
