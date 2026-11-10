"""Phrase-aware ICP parsing and matching: the semantic layer between a raw ICP
string ("Sustainability Consultancy for SMEs") and term matching in discovery.

The bag-of-words tokenizer treats every ICP word as independent evidence, so a
generic consulting page "verifies" a sustainability-consultancy ICP by matching
"consultancy" alone. This module keeps words that belong together TOGETHER: it
splits the ICP into ordered noun-phrase chunks, separates the core concept from
qualifiers ("for SMEs" names an audience, not an industry), and evidences a
multi-word core only as a phrase or as full token co-occurrence — never on a
single word.

No POS tagger and no new dependencies: the open word classes (nouns/adjectives)
need no dictionary, and the words that *separate* phrases — prepositions,
conjunctions, determiners — are a small closed class enumerated below. Pure
stdlib; imports nothing from opencold.discovery (discovery imports from here).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# Too-generic ICP words: they stay inside a chunk for phrase matching ("software
# companies" is still a phrase) but never become required evidence on their own.
GENERIC_ICP_TERMS = {
    "startup",
    "startups",
    "company",
    "companies",
    "tool",
    "tools",
    "early",
    "software",
    "platform",
    "business",
}

# The stopwords the flat tokenizer (discovery._icp_terms) has always dropped.
ICP_STOPWORDS = {"and", "for", "the", "with", "that", "this"}

# Closed-class chunk boundaries. A qualifier marker flips parsing into qualifier
# mode permanently: everything after "for"/"serving"/"in"/... describes audience,
# geography, or focus — supporting context, not the core industry concept.
QUALIFIER_MARKERS = {
    "for", "serving", "targeting", "helping", "catering",
    "in", "within", "across", "near", "at", "around", "from", "to",
    "toward", "towards",
    "based", "located", "operating",
    "with", "without", "via", "by",
    "who", "that", "which", "whose",
    "focused", "focusing", "specializing", "specialising", "on",
}

# "of" closes the current sub-chunk but its complement stays core:
# "Manufacturers of Industrial Pumps" is one concept in two sub-chunks.
CORE_LINKERS = {"of"}

# Skipped without breaking the chunk: B2B coordinations are overwhelmingly fixed
# compounds ("health and safety", "oil and gas") — splitting on "and" would
# re-create the single-word-evidence bug once per branch.
TRANSPARENT = {"and", "or", "the", "a", "an", "&"}

# Common inflectional suffixes, longest-first so "landscapers" -> "ers" (not "er"+"s").
_STEM_SUFFIXES = ("ings", "ing", "ers", "er", "ed", "es", "s")


def stem(word: str) -> str:
    """Light inflectional stemmer so morphological variants of an ICP term collapse
    to one form: landscape / landscaping / landscaper / landscapes / landscaped ->
    'landscap'. Deliberately conservative — only strips a common suffix when ≥4 stem
    characters remain (guards short words like 'caring'->'car'), then normalises a
    trailing 'e'. Not a full Porter stemmer; predictability beats coverage here."""
    w = word.lower()
    for suf in _STEM_SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            w = w[: -len(suf)]
            break
    if len(w) >= 5 and w.endswith("e"):
        w = w[:-1]
    return w


@dataclass(frozen=True)
class Chunk:
    tokens: tuple[str, ...]      # ordered, lowercased, hyphens preserved
    required: tuple[bool, ...]   # False for generic/stopword tokens
    role: str                    # "core" | "qualifier"

    @property
    def head(self) -> str:
        """Last token: the head noun of an English noun phrase ("sustainability
        CONSULTANCY"). The evidence gate treats all required tokens equally; the
        head is exposed for query building and diagnostics."""
        return self.tokens[-1]

    @property
    def required_tokens(self) -> tuple[str, ...]:
        return tuple(t for t, r in zip(self.tokens, self.required) if r)


@dataclass(frozen=True)
class IcpProfile:
    icp: str
    chunks: tuple[Chunk, ...]
    core_tokens: tuple[str, ...]       # ordered required core tokens (gate set R)
    qualifier_tokens: tuple[str, ...]  # ordered required qualifier tokens
    # Multi-token core chunks with ≥1 required token: the units for phrase
    # matching, whole-phrase translation, and phrase-level Datamuse expansion.
    core_phrases: tuple[tuple[str, ...], ...]


@lru_cache(maxsize=128)
def parse_icp(icp: str) -> IcpProfile:
    """Split an ICP into ordered chunks with a one-way core->qualifier state
    machine. Transparent words are skipped in place, qualifier markers close the
    chunk and flip the state for good, and "of" closes a sub-chunk without
    leaving core (of-attachment)."""
    raw = [t.lower() for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-&]*", icp or "") if len(t) >= 2]
    chunks: list[Chunk] = []
    state = "core"
    current: list[str] = []

    def close() -> None:
        if current:
            required = tuple(
                t not in GENERIC_ICP_TERMS and t not in ICP_STOPWORDS for t in current
            )
            chunks.append(Chunk(tokens=tuple(current), required=required, role=state))
            current.clear()

    for tok in raw:
        if tok in TRANSPARENT:
            continue
        if tok in QUALIFIER_MARKERS:
            close()
            state = "qualifier"
            continue
        if tok in CORE_LINKERS:
            close()
            continue
        current.append(tok)
    close()

    def ordered_required(role: str) -> tuple[str, ...]:
        seen: set[str] = set()
        out: list[str] = []
        for chunk in chunks:
            if chunk.role != role:
                continue
            for t in chunk.required_tokens:
                if t not in seen:
                    seen.add(t)
                    out.append(t)
        return tuple(out)

    return IcpProfile(
        icp=icp,
        chunks=tuple(chunks),
        core_tokens=ordered_required("core"),
        qualifier_tokens=ordered_required("qualifier"),
        core_phrases=tuple(
            c.tokens for c in chunks
            if c.role == "core" and len(c.tokens) >= 2 and any(c.required)
        ),
    )


def text_words(text: str) -> list[str]:
    """Ordered alphanumeric words of `text`, lowercased. Hyphens and URL-slug
    separators split here, so "sustainability-consulting" yields adjacent words
    and phrase matching covers slugs for free."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def phrase_hit(chunk_tokens: tuple[str, ...], words: list[str], stems: list[str] | None = None) -> bool:
    """True when the chunk appears in `words` as an in-order stem sequence with at
    most 2 intervening words ("health AND safety consultants" still hits; tokens
    scattered across a page do not — that is co-occurrence, judged separately) OR
    as one concatenated compound word ("paper mill" ~ "papermills")."""
    if not chunk_tokens or not words:
        return False
    if stems is None:
        stems = [stem(w) for w in words]
    targets = [stem(t.replace("-", "")) for t in chunk_tokens]
    n = len(stems)
    for start, s in enumerate(stems):
        if s != targets[0]:
            continue
        pos = start
        ok = True
        for target in targets[1:]:
            nxt = next((j for j in range(pos + 1, min(pos + 4, n)) if stems[j] == target), None)
            if nxt is None:
                ok = False
                break
            pos = nxt
        if ok:
            return True
    concat = "".join(t.replace("-", "") for t in chunk_tokens)
    concat_stem = stem(concat)
    return any(ws == concat or ws == concat_stem for ws in set(stems))


def _term_in_text(term: str, stem_set: set[str], low_text: str) -> bool:
    """One derived term against the text: whole-word stem match (morphology) or
    ≥4-char literal substring (hyphenated/compound terms and multi-word phrases
    like "gestion des déchets"). Derived terms are machine-generated, so short
    ones never substring-match — "urn" sits inside "journalism". Mirrors
    discovery._icp_match for a single term."""
    return stem(term) in stem_set or (len(term) >= 4 and term in low_text)


def token_evidenced(
    token: str,
    word_set: set[str],
    stem_set: set[str],
    low_text: str,
    derived: set[str] | None = None,
) -> bool:
    """One ICP token against the text. Evidence comes from the token's own stem,
    a literal substring for ≥3-char tokens ("tech" in "fintech" — the flat
    tokenizer never produced shorter terms, and 2-char tokens like "ai" would
    match inside unrelated words), a bare-plural fallback the stemmer is too
    conservative for ("SMEs" ~ "SME"), or any term derived from this token
    (native translations, expansion-cluster members)."""
    if stem(token) in stem_set:
        return True
    if len(token) >= 3 and token in low_text:
        return True
    if len(token) >= 3 and token.endswith("s") and token[:-1] in word_set:
        return True
    return any(_term_in_text(d, stem_set, low_text) for d in (derived or set()))


@dataclass(frozen=True)
class CoreMatch:
    phrase_chunks: tuple[tuple[str, ...], ...]  # core chunks that hit as phrases
    evidenced: frozenset[str]                   # required core tokens evidenced
    required: frozenset[str]                    # gate set R
    matched_qualifiers: tuple[str, ...]         # qualifier tokens evidenced
    confirmed: bool                             # every required core token evidenced


def evidence_core(
    profile: IcpProfile,
    text: str,
    provenance: dict[str, set[str]] | None = None,
) -> CoreMatch:
    """Evidence the ICP core against `text`. A phrase hit on a chunk evidences all
    of that chunk's required tokens at once; remaining tokens are checked
    individually (own form or provenance class). `confirmed` is the all-core-tokens
    rule: partial hits never confirm a multi-word core."""
    words = text_words(text)
    stems = [stem(w) for w in words]
    word_set = set(words)
    stem_set = set(stems)
    low = (text or "").lower()
    prov = provenance or {}

    phrase_chunks: list[tuple[str, ...]] = []
    evidenced: set[str] = set()
    for chunk_tokens in profile.core_phrases:
        if phrase_hit(chunk_tokens, words, stems):
            phrase_chunks.append(chunk_tokens)
            for chunk in profile.chunks:
                if chunk.tokens == chunk_tokens:
                    evidenced.update(chunk.required_tokens)

    required = set(profile.core_tokens)
    for tok in sorted(required - evidenced):
        if token_evidenced(tok, word_set, stem_set, low, prov.get(tok)):
            evidenced.add(tok)

    matched_qualifiers = tuple(
        t for t in profile.qualifier_tokens
        if token_evidenced(t, word_set, stem_set, low, prov.get(t))
    )
    return CoreMatch(
        phrase_chunks=tuple(phrase_chunks),
        evidenced=frozenset(evidenced),
        required=frozenset(required),
        matched_qualifiers=matched_qualifiers,
        confirmed=bool(required) and required <= evidenced,
    )
