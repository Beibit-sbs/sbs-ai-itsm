"""PII redaction helpers for AI provider inputs.

The strategy is intentionally conservative: we prefer to redact more than
necessary rather than leak. Redactions are reversible via the returned token
map so a downstream response can be unredacted if it echoes tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s()]{6,}\d)")
_IIN_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
_IP_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


@dataclass(slots=True)
class RedactionResult:
    text: str
    tokens: dict[str, str]


def redact_pii(text: str) -> RedactionResult:
    if not text:
        return RedactionResult(text=text or "", tokens={})

    tokens: dict[str, str] = {}

    def _replace(pattern: re.Pattern[str], prefix: str, source: str) -> str:
        counter = {"n": 0}

        def _sub(match: re.Match[str]) -> str:
            counter["n"] += 1
            token = f"<{prefix}_{counter['n']}>"
            tokens[token] = match.group(0)
            return token

        return pattern.sub(_sub, source)

    working = text
    working = _replace(_EMAIL_RE, "EMAIL", working)
    working = _replace(_IP_RE, "IP", working)
    working = _replace(_CARD_RE, "CARD", working)
    working = _replace(_IIN_RE, "IIN", working)
    working = _replace(_PHONE_RE, "PHONE", working)
    return RedactionResult(text=working, tokens=tokens)


def restore_pii(text: str, tokens: dict[str, str]) -> str:
    if not text or not tokens:
        return text or ""
    result = text
    for token, original in tokens.items():
        result = result.replace(token, original)
    return result


__all__ = ["RedactionResult", "redact_pii", "restore_pii"]
