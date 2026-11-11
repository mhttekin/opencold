"""Native-language ICP term translation and translate-on-miss enrichment localization."""

from __future__ import annotations

import re

from opencold import enricher, icp_phrases, translator
from opencold.discovery_icp_score import _icp_evidence, _icp_terms
from opencold.icp_phrases import stem as _stem

# Function words that phrase translations leak as standalone tokens ("waste
# management" -> "gestion DES déchets"). A leaked article/preposition matches any
# text in that language, so it must never become a matcher term. Tokens under 4
# chars are dropped outright; this list covers the common >=4-char leaks.
_NATIVE_FUNCTION_WORDS = {
    "pour",
    "avec",
    "dans",
    "sans",
    "sous",
    "chez",
    "leur",
    "elles",
    "vers",
    "para",
    "como",
    "sobre",
    "entre",
    "desde",
    "hasta",
    "unas",
    "unos",
    "della",
    "delle",
    "degli",
    "dello",
    "dalla",
    "nella",
    "alla",
    "eine",
    "einer",
    "eines",
    "einem",
    "einen",
    "nach",
    "über",
    "unter",
    "voor",
    "naar",
    "deze",
    "onder",
    "için",
    "veya",
}


def _translated_term_ok(term: str, translated: str, target_lang: str) -> bool:
    """Round-trip validation of one term translation. Keyless providers sometimes
    return a wrong translation-memory match ("recycling" -> ar "water treatment"):
    translate the result back to English and require a shared stem with the original
    term. When the round trip is unavailable (provider down / echoes its input), keep
    the term — this tier is best-effort, and a dead provider must not erase it."""
    back = translator.translate(translated, "en", source=target_lang)
    if not back or back.strip().lower() == translated.strip().lower():
        return True
    back_stems = {_stem(w) for w in re.findall(r"[a-z0-9]+", back.lower())}
    return any(_stem(w) in back_stems for w in re.findall(r"[a-z0-9]+", term.lower()))


def _translate_one(term: str, target_lang: str) -> tuple[list[str], str]:
    """One English term -> (kept native tokens, full native phrase or ""). The
    phrase is non-empty only for multi-word results with at least one kept token
    ("waste management" -> "gestion des déchets"). Precision-filtered: alternative
    lists ("gaspillage/gaspiller/perdre/...") collapse to their first entry,
    >3-token results are provider noise and dropped, a round-trip check kills wrong
    translation-memory matches, and short/function-word tokens are dropped — a
    leaked article like "des" matches every text in its language."""
    translated = translator.translate(term, target_lang, source="en")
    if not translated or translated.lower() == term:
        return [], ""
    translated = re.split(r"[/;|]", translated)[0].strip()
    tokens = re.findall(r"\w[\w\-]{2,}", translated.lower(), re.UNICODE)
    if not tokens or len(tokens) > 3:
        return [], ""
    if not _translated_term_ok(term, translated, target_lang):
        return [], ""
    kept = [t for t in tokens if len(t) >= 4 and t not in _NATIVE_FUNCTION_WORDS]
    phrase = " ".join(tokens) if len(tokens) > 1 and kept else ""
    return kept, phrase


def _translate_terms(terms: set[str], target_lang: str) -> set[str]:
    """Native-language forms of an English term set: translate each term and keep the
    result tokens plus, for multi-word results, the full phrase (matched via the
    literal-substring branch). Best-effort and cached; returns an empty set when
    translation is unavailable. Unicode-aware so native tokens stay intact (e.g.
    "ürünleri")."""
    out: set[str] = set()
    for term in terms:
        kept, phrase = _translate_one(term, target_lang)
        out.update(kept)
        if phrase:
            out.add(phrase)
    return out


def _translate_icp_terms(icp: str, target_lang: str) -> set[str]:
    """Native-language ICP terms for matching home-language sites (e.g. "timber" ->
    "kereste"), so a home-language site matches without translating its text first."""
    return _translate_terms(_icp_terms(icp), target_lang)


def _translate_profile(
    profile: "icp_phrases.IcpProfile", target_lang: str
) -> tuple[set[str], set[str], dict[str, set[str]]]:
    """Native-language matcher terms for one ICP profile, with attribution:
    (strong flat, weak flat, token -> native terms).

    Core tokens translate to strong terms attributed to themselves; qualifier
    tokens ("for SMEs") translate to weak terms only — an audience word must not
    verify an industry. Each multi-token core phrase is ALSO translated whole:
    languages like Dutch compound it into one word ("sustainability consultancy"
    -> "duurzaamheidsadvies") that per-token translation can never produce, and
    that single word co-evidences the entire chunk. A multi-word phrase result
    keeps multi-token attribution only as the full phrase; its individual tokens
    go weak — a leaked "advies" must never co-evidence "sustainability"."""
    strong: set[str] = set()
    weak: set[str] = set()
    provenance: dict[str, set[str]] = {}

    def attribute(token: str, terms: set[str]) -> None:
        if terms:
            provenance.setdefault(token, set()).update(terms)

    for token in profile.core_tokens:
        kept, phrase = _translate_one(token, target_lang)
        native = set(kept) | ({phrase} if phrase else set())
        strong |= native
        attribute(token, native)
    for token in profile.qualifier_tokens:
        kept, phrase = _translate_one(token, target_lang)
        native = set(kept) | ({phrase} if phrase else set())
        weak |= native
        attribute(token, native)
    for chunk in profile.core_phrases:
        required = [t for t in chunk if t in profile.core_tokens]
        kept, phrase = _translate_one(" ".join(chunk), target_lang)
        if phrase:
            # Multi-word native phrase: only the whole phrase speaks for the chunk.
            strong.add(phrase)
            weak.update(kept)
            for token in required:
                attribute(token, {phrase})
        elif len(kept) == 1:
            # Single native compound: one word covers the whole concept.
            strong.update(kept)
            for token in required:
                attribute(token, set(kept))
    return strong, weak, provenance


def _translate_expansion_terms(terms: set[str], target_lang: str) -> tuple[set[str], set[str]]:
    """Native forms of expansion-cluster terms: (all forms, attribution-safe subset).
    A multi-word native result is attribution-safe only as the full phrase — its
    individual tokens are common words ("professional services" -> "zakelijke
    dienstverlening" leaks "zakelijke" = plain "business") that would let any site
    in that language co-evidence a core token. Cluster terms are already one
    semantic hop from the ICP; their translations must not drift further."""
    flat: set[str] = set()
    safe: set[str] = set()
    for term in terms:
        kept, phrase = _translate_one(term, target_lang)
        flat.update(kept)
        if phrase:
            flat.add(phrase)
            safe.add(phrase)
        else:
            safe.update(kept)
    return flat, safe


def _localize_enrichment(
    enrichment: dict,
    icp: str,
    extra_terms: set[str] | None,
    provenance: dict[str, set[str]] | None = None,
) -> dict:
    """Translate-on-miss: when neither English nor native ICP terms are evidenced
    (likely a home-language site the English path missed), translate this company's
    distilled facts into English in place, so downstream matching, the LLM judge,
    and the CSV all read English. Facts are short and cached, so volume stays low."""
    if _icp_evidence(icp, enrichment, extra_terms, provenance=provenance):
        return enrichment
    summary = enrichment.get("company_summary", "")
    facts = enrichment.get("personalization_facts", "")
    if not summary and not facts:
        return enrichment
    localized = dict(enrichment)
    if summary:
        localized["company_summary"] = translator.translate(summary, "en", source="auto")
    if facts:
        parts = facts.split(enricher.FACT_SEPARATOR)
        translated = translator.translate_many(parts, "en", source="auto")
        localized["personalization_facts"] = enricher.FACT_SEPARATOR.join(translated)
    return localized
