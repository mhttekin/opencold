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

MAX_EXPANSION_TERMS = 24       # hard cap on the returned set (bounds drift)
DATAMUSE_MAX = 20              # words requested per Datamuse relation
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

# Process-wide disk-cache mirror; None = not yet loaded.
_DISK_CACHE: dict[str, list[str]] | None = None


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


def _good_candidate(w: str) -> bool:
    """Quality gate for network/LLM candidates: short-ish English noun-ish terms only."""
    if not w or len(w) < 3 or len(w.split()) > 3:
        return False
    try:
        from opencold.discovery import GENERIC_ICP_TERMS
    except Exception:
        GENERIC_ICP_TERMS = set()
    if w in GENERIC_ICP_TERMS or w in _EXTRA_STOPWORDS:
        return False
    return bool(_WORD_RE.fullmatch(w))


def _lexicon_terms(icp: str) -> set[str]:
    """Tier 1: curated lexicon, looked up stem/substring-aware so "timber merchants"
    keys to "timber"."""
    try:
        from opencold.discovery import _stem
    except Exception:
        def _stem(w):  # pragma: no cover - discovery always importable in practice
            return w
    from opencold import icp_synonyms
    lex = icp_synonyms.merged_lexicon()
    low = (icp or "").lower()
    core_stems = {_stem(t) for t in _core_tokens(icp)}
    out: set[str] = set()
    for key, terms in lex.items():
        # Single-word keys match by stem (whole word) — a substring test would let a
        # short symmetric key like "ev"/"tax" hit inside "developer"/"taxi". Multi-word
        # keys ("timber merchant", "real estate") match as a substring of the ICP.
        if _stem(key) in core_stems or (" " in key and key in low):
            out |= terms
    return out


def _datamuse(term: str) -> list[str]:
    """Tier 2: keyless Datamuse terms, returned in RELEVANCE order (means-like first,
    then associated; Datamuse ranks each list itself). Fail-silent (like _ddgs_search):
    any error on a relation yields nothing for that relation. Order matters — the
    caller fills the cap by relevance, so noisy low-ranked terms fall off the end."""
    out: list[str] = []
    seen: set[str] = set()
    term = (term or "").strip()
    if not term:
        return out
    for rel in ("ml", "rel_trg"):
        try:
            q = urllib.parse.urlencode({rel: term, "max": DATAMUSE_MAX})
            req = urllib.request.Request(f"https://api.datamuse.com/words?{q}",
                                         headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read(200_000).decode("utf-8", "replace"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            w = ((item.get("word") if isinstance(item, dict) else "") or "").lower().strip()
            if w not in seen and _good_candidate(w):
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


def _load_cache() -> dict[str, list[str]]:
    global _DISK_CACHE
    if _DISK_CACHE is None:
        try:
            data = json.loads(_cache_path().read_text(encoding="utf-8"))
            _DISK_CACHE = data if isinstance(data, dict) else {}
        except Exception:
            _DISK_CACHE = {}
    return _DISK_CACHE


def _save_cache(key: str, terms: set[str]) -> None:
    cache = _load_cache()
    cache[key] = sorted(terms)
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

def expand_icp(icp: str, *, use_llm: bool = True, provider: dict | None = None,
               use_datamuse: bool = True) -> set[str]:
    """English related-term set for `icp`, filtered, deduped, and capped to
    MAX_EXPANSION_TERMS. Never raises.

    Layered cheapest-first: curated lexicon (always) -> Datamuse (keyless network,
    default-on) -> one LLM call (only when `provider` is supplied & `use_llm`).
    Curated lexicon terms are prioritized into the cap; network/LLM terms fill the
    rest. Result is disk-cached under (normalized ICP, tier signature)."""
    icp = (icp or "").strip()
    if not icp:
        return set()
    core = _core_tokens(icp)
    llm_on = bool(use_llm and provider)
    sig = "l1" + ("d" if use_datamuse else "") + ("m" if llm_on else "")
    key = f"{_norm(icp)}|{sig}"

    cache = _load_cache()
    if key in cache:
        return set(cache[key])

    lex = _lexicon_terms(icp)
    llm = _llm_terms(icp, provider) if llm_on else set()
    dm: list[str] = []
    if use_datamuse:
        for tok in sorted(core):              # sorted core -> deterministic datamuse order
            dm += _datamuse(tok)

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

    out = set(result)
    _save_cache(key, out)
    return out


def curated_terms(icp: str) -> set[str]:
    """The curated-lexicon subset for `icp`. Used when translating expansion terms to a
    native language: only these are safe to translate — Datamuse-tail terms spawn
    generic native words (e.g. "alan") that cause false matches."""
    return _lexicon_terms(icp)


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
