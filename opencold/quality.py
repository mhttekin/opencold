"""Quality checks for generated outreach drafts."""

from __future__ import annotations

import re

from opencold.enricher import FACT_SEPARATOR


_GENERIC_PHRASES = (
    "i hope this email finds you well",
    "touch base",
    "synergy",
    "game-changer",
    "cutting-edge",
    "streamline",
    "reaching out",
    "i came across",
    "i was impressed",
    "i'd love to",
)


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text or "")


def _fact_tokens(facts: str) -> set[str]:
    tokens = {t.lower() for t in _words(facts) if len(t) > 5}
    return tokens


def evaluate_draft(subject: str, body: str, facts: str = "") -> list[str]:
    """Return warning codes for a generated email draft."""
    warnings = []
    body_lower = (body or "").lower()

    if not (subject or "").strip():
        warnings.append("missing_subject")
    if len(_words(body)) > 90:
        warnings.append("too_long")

    paragraphs = [p.strip() for p in (body or "").split("\n\n") if p.strip()]
    # Ignore the final sender-name sign-off if present.
    if len(paragraphs) > 3 and len(_words(paragraphs[-1])) <= 4:
        paragraphs = paragraphs[:-1]
    if len(paragraphs) != 3:
        warnings.append("not_three_paragraphs")

    if any(phrase in body_lower for phrase in _GENERIC_PHRASES):
        warnings.append("generic_or_spammy_phrase")

    tokens = _fact_tokens(facts)
    if tokens:
        body_tokens = {t.lower() for t in _words(body)}
        if not tokens.intersection(body_tokens):
            warnings.append("no_grounded_fact_used")
    else:
        warnings.append("no_grounded_facts_available")

    return warnings


def merge_warnings(*groups: str | list[str]) -> str:
    """Merge warning strings/lists into a stable CSV-safe warning field."""
    merged = []
    for group in groups:
        values = group.split(FACT_SEPARATOR) if isinstance(group, str) else group
        for value in values:
            value = value.strip()
            if value and value not in merged:
                merged.append(value)
    return FACT_SEPARATOR.join(merged)
