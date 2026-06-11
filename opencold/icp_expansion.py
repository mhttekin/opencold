"""Semantic ICP expansion: turn one ICP ("Timber") into related English terms
("wood", "lumber", "sawmill", ...) that widen search recall and matching.

Keyless-by-default and degrades gracefully, mirroring the translator/_ddgs_search
philosophy: every tier is best-effort and returns an empty set on failure, so a run
with no network, no LLM provider, and no extra packages still gets the curated
lexicon (Tier 1).

Tiers (cheapest / most-reliable first):
  1. Curated lexicon (icp_synonyms.py)         — offline, keyless, ALWAYS ON.
  2. Datamuse means-like / associated terms     — keyless network (no API key), default-on, fail-silent.
  3. One-shot LLM expansion (generator.complete) — optional, only when a provider is supplied
                                                   (the user's key on the CLI, or a cheap hosted
                                                   SLM / local Ollama via the `proxy` provider).

One expansion per run, persisted to ``~/.opencold/icp_expansions.json`` keyed by the
normalized ICP plus a tier signature, so a distinct ICP costs at most one network/LLM
round-trip per signature. (A future embeddings relevance-filter tier can slot in
behind an optional ``opencold[expansion]`` extra; it would re-rank candidates, not
generate them.)

discovery imports are done lazily inside functions to avoid an import cycle.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from opencold import icp_phrases

MAX_EXPANSION_TERMS = 24       # hard cap on the returned set (bounds drift)
DATAMUSE_MAX = 20              # words requested per Datamuse relation
# Corpus frequency ceiling (occurrences per million words, Datamuse md=f) for a
# Datamuse term to become a MATCHER term. Everyday English appears on any business
# page regardless of industry — measured: ml("plumbing") includes water(278)/
# line(187)/health(161), enough for an insurance site to pass the weak-evidence
# gate; specific industry terms (sawmill 0.5, viticulture, aeroponics) sit far
# below. Commonness is the harm even when topically relevant ("delivery" for a
# freight ICP matches every webshop).
DATAMUSE_MAX_FREQ = 15.0
EXPANSION_QUERY_CAP = 3        # top-N expansion terms that each get ONE search query
_TIMEOUT = 4.0
_UA = "opencold/0.1 (icp expansion)"

# Too-generic words to drop from the network/LLM tiers (the curated lexicon is
# trusted as-is and is NOT passed through this filter).
_EXTRA_STOPWORDS = {
    "service", "services", "solution", "solutions", "industry", "industries",
    "sector", "market", "markets", "supplier", "suppliers", "provider", "providers",
    "firm", "firms", "group", "business", "businesses", "company", "companies",
    "best", "top", "near", "online", "local", "global", "international", "leading",
    "quality", "professional", "product", "products",
    # common function words (a Datamuse/LLM slip would otherwise match everything)
    "the", "and", "for", "with", "that", "this", "are", "our", "you", "your",
    "from", "not", "their", "they", "its", "all", "any", "other", "such",
}

_WORD_RE = re.compile(r"[a-z][a-z \-]+")

# Process-wide disk-cache mirror; None = not yet loaded. Values are v2 dicts
# ({"flat": [...], "by_token": {...}}); inert v1 list entries may linger on disk.
_DISK_CACHE: dict[str, object] | None = None


# ---------------------------------------------------------------------------
# Helpers (lazy discovery imports avoid an import cycle)
# ---------------------------------------------------------------------------

def _core_tokens(icp: str) -> set[str]:
    """Original ICP tokens (reuses the discovery tokenizer so behaviour matches)."""
    try:
        from opencold.discovery import _icp_terms
        return _icp_terms(icp)
    except Exception:
        return {t for t in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", (icp or "").lower())}


def _norm(icp: str) -> str:
    """Stable cache key core: sorted core tokens (order/casing/stopwords insensitive)."""
    return " ".join(sorted(_core_tokens(icp)))


def _norm_v2(icp: str) -> str:
    """v2 cache key core: required core tokens IN ORDER, then the remaining flat
    tokens sorted. Order matters now — phrase-level Datamuse queries depend on it,
    so "Consultancy for Sustainability" and "Sustainability Consultancy" must not
    share a cache entry."""
    profile = icp_phrases.parse_icp(icp)
    rest = sorted(set(_core_tokens(icp)) - set(profile.core_tokens))
    return " ".join(profile.core_tokens) + "//" + " ".join(rest)


_GEO_TERMS: frozenset[str] | None = None


def _geo_terms() -> frozenset[str]:
    """Country names, aliases, demonyms, and major cities. Geography is never
    industry evidence — Datamuse associates commodity phrases with their producer
    countries ("coffee exporter" -> uganda/ethiopia/brazil), and a region word as
    a matcher term makes every local site "match" the ICP. Region fit is judged
    by its own layer."""
    global _GEO_TERMS
    if _GEO_TERMS is None:
        terms: set[str] = set()
        try:
            from opencold import regions_data as rd
            for country, info in rd.COUNTRIES.items():
                terms.add(country)
                for field in ("aliases", "demonyms", "cities"):
                    terms.update(info.get(field, []))
        except Exception:
            pass
        _GEO_TERMS = frozenset(terms)
    return _GEO_TERMS


def _good_candidate(w: str) -> bool:
    """Quality gate for network/LLM candidates: short-ish English noun-ish terms only."""
    if not w or len(w) < 3 or len(w.split()) > 3:
        return False
    if w in icp_phrases.GENERIC_ICP_TERMS or w in _EXTRA_STOPWORDS or w in _geo_terms():
        return False
    return bool(_WORD_RE.fullmatch(w))


def _lexicon_terms_grouped(icp: str) -> tuple[set[str], dict[str, set[str]]]:
    """Tier 1: curated lexicon, looked up stem/substring-aware so "timber merchants"
    keys to "timber". Returns (flat terms, ICP-token -> terms attribution): cluster
    co-members evidence the specific ICP token that keyed them, so downstream
    matching knows "advisory" speaks for "consultancy" and not for "sustainability".
    A multi-word key ("waste management") attributes to every ICP token it contains
    — the cluster is a trusted phrase-level equivalence."""
    from opencold import icp_synonyms
    lex = icp_synonyms.merged_lexicon()
    low = (icp or "").lower()
    profile = icp_phrases.parse_icp(icp)
    tokens = list(dict.fromkeys(profile.core_tokens + profile.qualifier_tokens))
    stem_to_tokens: dict[str, list[str]] = {}
    for t in tokens:
        stem_to_tokens.setdefault(icp_phrases.stem(t), []).append(t)
    flat: set[str] = set()
    by_token: dict[str, set[str]] = {}
    for key, terms in lex.items():
        # Single-word keys match by stem (whole word) — a substring test would let a
        # short symmetric key like "ev"/"tax" hit inside "developer"/"taxi". Multi-word
        # keys ("timber merchant", "real estate") match as a substring of the ICP.
        if " " not in key:
            matched = stem_to_tokens.get(icp_phrases.stem(key), [])
        elif key in low:
            key_stems = {icp_phrases.stem(w) for w in key.split()}
            matched = [t for t in tokens if icp_phrases.stem(t) in key_stems]
        else:
            matched = []
        if matched or (" " in key and key in low):
            flat |= terms
        for tok in matched:
            by_token.setdefault(tok, set()).update(terms)
    return flat, by_token


def _lexicon_terms(icp: str) -> set[str]:
    """Tier 1 flat view (kept for callers that don't need attribution)."""
    return _lexicon_terms_grouped(icp)[0]


def _word_freq(item: dict) -> float:
    """Corpus frequency (per million words) from a Datamuse md=f tag; 0 when absent."""
    for tag in item.get("tags") or []:
        if isinstance(tag, str) and tag.startswith("f:"):
            try:
                return float(tag[2:])
            except ValueError:
                pass
    return 0.0


def _datamuse(term: str, rels: tuple[str, ...] = ("ml", "rel_trg")) -> list[str]:
    """Tier 2: keyless Datamuse terms, returned in RELEVANCE order (means-like first,
    then associated; Datamuse ranks each list itself). Fail-silent (like _ddgs_search):
    any error on a relation yields nothing for that relation. Order matters — the
    caller fills the cap by relevance, so noisy low-ranked terms fall off the end.
    Everyday-English results (corpus frequency >= DATAMUSE_MAX_FREQ, fetched on the
    same request via md=f) are dropped — they match any page in any industry."""
    out: list[str] = []
    seen: set[str] = set()
    term = (term or "").strip()
    if not term:
        return out
    for rel in rels:
        try:
            q = urllib.parse.urlencode({rel: term, "max": DATAMUSE_MAX, "md": "f"})
            req = urllib.request.Request(f"https://api.datamuse.com/words?{q}",
                                         headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read(200_000).decode("utf-8", "replace"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            w = (item.get("word") or "").lower().strip()
            if w in seen or not _good_candidate(w):
                continue
            if _word_freq(item) >= DATAMUSE_MAX_FREQ:
                continue
            seen.add(w)
            out.append(w)
    return out


_EXPAND_SYSTEM = (
    "You output ONLY compact JSON, no prose, no code fences. Given an industry or "
    "profile, list closely-related industry, sub-sector, product, and material terms "
    "a B2B buyer would search to find such companies."
)


def _llm_terms(icp: str, provider: dict) -> set[str]:
    """Tier 3: one short LLM call. Reuses generator.complete + _parse_json_object.
    Fail-silent. `provider` may be a paid key OR a local/hosted SLM via the proxy type."""
    try:
        from opencold import generator as _gen
        from opencold.discovery import _parse_json_object
    except Exception:
        return set()
    user = (
        f'Industry/profile: "{icp}"\n'
        "Return up to 15 closely-related English terms (synonyms, sub-sectors, "
        "products, materials). Single words or short noun phrases, no sentences.\n"
        'Output JSON exactly: {"terms": ["...", "..."]}'
    )
    try:
        raw = _gen.complete(provider, _EXPAND_SYSTEM, user, max_tokens=256)
    except Exception:
        return set()
    data = _parse_json_object(raw)
    out: set[str] = set()
    for t in (data.get("terms", []) if isinstance(data, dict) else []):
        if isinstance(t, str):
            w = t.lower().strip()
            if _good_candidate(w):
                out.add(w)
    return out


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------

def _cache_path():
    from opencold import config
    return config.CONFIG_DIR / "icp_expansions.json"


def _load_cache() -> dict:
    global _DISK_CACHE
    if _DISK_CACHE is None:
        try:
            data = json.loads(_cache_path().read_text(encoding="utf-8"))
            _DISK_CACHE = data if isinstance(data, dict) else {}
        except Exception:
            _DISK_CACHE = {}
    return _DISK_CACHE


def _save_cache(key: str, value) -> None:
    cache = _load_cache()
    cache[key] = value
    try:
        from opencold import config
        config._ensure_dir()
        _cache_path().write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    except Exception:
        pass  # cache write is best-effort; never fatal


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class ExpansionResult:
    """Expansion terms plus provenance: `flat` is the classic capped set; `by_token`
    maps each ICP token to the derived terms that evidence IT specifically — the
    attribution the phrase-aware gate needs so "advisory" can vouch only for
    "consultancy", never for "sustainability"."""
    flat: set[str] = field(default_factory=set)
    by_token: dict[str, set[str]] = field(default_factory=dict)


def expand_icp_grouped(icp: str, *, use_llm: bool = True, provider: dict | None = None,
                       use_datamuse: bool = True) -> ExpansionResult:
    """English related terms for `icp` with per-token attribution, filtered, deduped,
    and capped to MAX_EXPANSION_TERMS. Never raises.

    Layered cheapest-first: curated lexicon (always) -> Datamuse (keyless network,
    default-on) -> one LLM call (only when `provider` is supplied & `use_llm`).
    Curated lexicon terms are prioritized into the cap; network/LLM terms fill the
    rest. Attribution: only the trusted tiers carry it — lexicon clusters and
    per-token Datamuse means-like results. Phrase-level Datamuse, per-token
    associations, and LLM terms stay flat-only: a lone "consulting" from the
    phrase query "sustainability consultancy" must not co-evidence both tokens,
    and an association like coffee->"urn" must not evidence "coffee". Result is
    disk-cached under (ordered core tokens, tier signature)."""
    icp = (icp or "").strip()
    if not icp:
        return ExpansionResult()
    core = _core_tokens(icp)
    llm_on = bool(use_llm and provider)
    sig = "l1" + ("d" if use_datamuse else "") + ("m" if llm_on else "")
    # The version stamp also invalidates on lexicon edits — cached by_token holds
    # attributed cluster members, so a stale entry resurrects removed terms.
    key = f"{_norm_v2(icp)}|v6{sig}"

    cached = _load_cache().get(key)
    if isinstance(cached, dict):
        return ExpansionResult(
            flat=set(cached.get("flat", [])),
            by_token={t: set(v) for t, v in cached.get("by_token", {}).items()},
        )

    lex, by_token = _lexicon_terms_grouped(icp)
    llm = _llm_terms(icp, provider) if llm_on else set()
    dm: list[str] = []
    if use_datamuse:
        # Trustworthiness order into the cap. Per-token means-like first: synonym
        # grade, safe to attribute. Then phrase-level neighbours (Datamuse accepts
        # multi-word ml=; on-concept but unattributed — "coffee exporter" returns
        # producer countries and other context, not synonyms of either word). Loose
        # per-token associations (rel_trg: coffee -> urn/cup) come last and are
        # never attributed — they must not co-evidence a core token.
        assoc: list[str] = []
        for tok in sorted(core):              # sorted core -> deterministic datamuse order
            hits = _datamuse(tok, rels=("ml",))
            dm += hits
            if hits:
                by_token.setdefault(tok, set()).update(hits)
            assoc += _datamuse(tok, rels=("rel_trg",))
        for chunk in icp_phrases.parse_icp(icp).core_phrases:
            if len(chunk) <= 3:
                dm += _datamuse(" ".join(chunk))
        dm += assoc

    # Priority into the cap: curated lexicon (trusted) -> LLM (high quality) -> Datamuse
    # in relevance order. Drop original ICP tokens; dedup preserving order; cap.
    lex_llm = lex | llm
    ordered = sorted(lex) + sorted(llm - lex) + [w for w in dm if w not in lex_llm]
    result: list[str] = []
    seen: set[str] = set()
    for t in ordered:
        if not t or t in core or t in seen:
            continue
        seen.add(t)
        result.append(t)
        if len(result) >= MAX_EXPANSION_TERMS:
            break

    flat = set(result)
    # The two views must never disagree: attribution only for terms that survived
    # the cap.
    by_token = {tok: terms & flat for tok, terms in by_token.items() if terms & flat}
    _save_cache(key, {"flat": sorted(flat),
                      "by_token": {t: sorted(v) for t, v in sorted(by_token.items())}})
    return ExpansionResult(flat=flat, by_token=by_token)


def expand_icp(icp: str, *, use_llm: bool = True, provider: dict | None = None,
               use_datamuse: bool = True) -> set[str]:
    """Flat view of expand_icp_grouped (kept for callers without attribution needs)."""
    return expand_icp_grouped(icp, use_llm=use_llm, provider=provider,
                              use_datamuse=use_datamuse).flat


def curated_terms(icp: str) -> set[str]:
    """The curated-lexicon subset for `icp`. Used when translating expansion terms to a
    native language: only these are safe to translate — Datamuse-tail terms spawn
    generic native words (e.g. "alan") that cause false matches."""
    return _lexicon_terms(icp)


def curated_terms_grouped(icp: str) -> dict[str, set[str]]:
    """Curated-lexicon terms keyed by the ICP token they evidence (the translation
    path translates per token so native forms stay attributed)."""
    return _lexicon_terms_grouped(icp)[1]


def expansion_queries(expansion: set[str], region: str, cap: int = EXPANSION_QUERY_CAP) -> list[str]:
    """Bounded search queries: ONE template per top-N expansion term. Curated lexicon
    terms are preferred for search (higher precision than Datamuse associations like
    "bush"/"geyser"); ties break alphabetically for reproducibility. Native translation
    is added downstream by the caller, so this returns English forms only."""
    region = (region or "").strip()
    if not region:
        return []
    try:
        from opencold import icp_synonyms
        lex_all = set().union(*icp_synonyms.merged_lexicon().values())
    except Exception:
        lex_all = set()
    ranked = sorted(expansion, key=lambda t: (t not in lex_all, t))
    return [f"{t} companies in {region}" for t in ranked[:cap] if t]
