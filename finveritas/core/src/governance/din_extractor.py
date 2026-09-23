"""Best-effort Director Identification Number (DIN) extraction from filings.

India's MCA assigns an 8-digit DIN to every company director. This is a
regex scan over whatever OCR/filing text is available — it is explicitly
best-effort (annual reports vary wildly in layout) and the UI always allows
manual entry/correction of the extracted names and DINs.
"""

from __future__ import annotations

import re

_DIN_RE = re.compile(r"\bDIN\s*[:\-]?\s*(\d{8})\b", re.IGNORECASE)
# "Jane Doe (DIN: 01234567)" / "Jane Doe, DIN 01234567" / "Jane Doe – DIN: 01234567"
_NAME_DIN_RE = re.compile(
    r"([A-Z][A-Za-z\.\s]{2,40}?)\s*[\(,\-–]\s*DIN\s*[:\-]?\s*(\d{8})",
)


def extract_directors(text: str) -> list[dict[str, str]]:
    """Best-effort [{name, din}] pairs found in `text`. Never raises; returns
    [] when nothing is recognisable — the caller should fall back to manual entry."""
    if not text:
        return []

    found: dict[str, str] = {}
    # Match line-by-line, never across a newline: the name-capture group's
    # character class includes \s (which matches "\n" too), so scanning the
    # whole blob at once lets a trailing title on one line ("... Chairman")
    # bleed into the start of the next director's name ("Chairman K Doe").
    for line in text.splitlines():
        for m in _NAME_DIN_RE.finditer(line):
            name = re.sub(r"\s+", " ", m.group(1)).strip(" .,-")
            din = m.group(2)
            if name and din:
                found[din] = name

    # Fallback: bare DIN mentions without a clearly adjacent name.
    for m in _DIN_RE.finditer(text):
        din = m.group(1)
        found.setdefault(din, "")

    return [{"name": name, "din": din} for din, name in found.items()]
