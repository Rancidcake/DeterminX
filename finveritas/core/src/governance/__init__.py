"""Executive Background / Governance Agent (section 17-18 of the V2 brief).

    Extract DIN from filings -> statutory lookup (MCA/SEBI/IBBI, behind an
    abstraction) -> governance findings -> LLM narrates alongside, never
    combined into the financial credibility score.

Governance is reported as its own PASS/WARN/FAIL/UNAVAILABLE status,
separate from Financial Credibility (section 18: "no-judgment reporting").
"""
