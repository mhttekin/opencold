"""Match an Ideal Customer Profile (ICP) to UK SIC industry codes.

Two dimensions matter:

1. **Subject** -- what the business is about (food, timber, insurance). SIC
   descriptions are bureaucratic ("Manufacture of ...", "Retail sale of ... in
   specialised stores"); we strip filler, reduce each to its industry-signal
   stems, and score against the ICP's core tokens (full weight) + expansion
   synonyms (half weight, mirroring discovery.score_company so a synonym-only
   hit never outranks a true ICP hit).

2. **Role** -- manufacture vs wholesale vs retail. The role words are NOT noise:
   "food manufacturing" and "food retail" want completely different SIC codes.
   We detect the role(s) the ICP asks for and the role each SIC implies (from
   its title), then: if the ICP names role(s), keep only those (plus role-less
   SICs); if it names none, rank manufacture > wholesale > retail. The caller
   can ask the user which role when the ICP is silent.

Fallback (the "what if nothing matches?" path): strict (subject >= min_score)
then relaxed (any positive overlap). A generic ICP ("manufacturing companies"),
whose only signal word is itself a role/filler word, is reported status="generic"
so the caller can ask the user to narrow the subject.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from opencold import icp_phrases, sic_categories
from opencold.icp_phrases import GENERIC_ICP_TERMS, stem, text_words
from opencold.sic_data import SIC_CODES
from opencold.sic_rank import BM25_WEIGHT, index_scores, match_status, role_bonus

CATEGORY_WEIGHT = 1.0  # a category member (food->meat) is full subject signal

# Bureaucratic filler stripped from SIC descriptions before subject matching.
SIC_FILLER: frozenset[str] = frozenset(
    {
        "activities",
        "activity",
        "of",
        "and",
        "or",
        "the",
        "for",
        "with",
        "in",
        "to",
        "other",
        "sale",
        "sales",
        "repair",
        "repairing",
        "maintenance",
        "services",
        "service",
        "nec",
        "general",
        "specialised",
        "specialized",
        "own",
        "operation",
        "operations",
        "operating",
        "related",
        "support",
        "supporting",
        "involving",
        "involved",
        "via",
        "by",
        "not",
        "elsewhere",
        "classified",
        "including",
        "etc",
        "products",
        "goods",
        "non",
        "items",
        "use",
        "based",
        "n",
        "e",
        "c",
    }
)
# "except" opens an exclusion clause ("(except rice)") whose excluded term we
# drop without losing the rest of the description.

# --- business role (manufacture / wholesale / retail / primary) ------------
# Role words are matched as EXACT tokens (not stems), so "fishing" (a primary-
# sector verb) never collides with "fish" (a food subject). Each role's set
# merges how users phrase it with how Companies House phrases it in SIC titles
# (e.g. "Processing and preserving of ...", "Agents involved in the sale of ...").
ROLE_WORDS: dict[str, frozenset[str]] = {
    "manufacture": frozenset(
        {
            "manufacture",
            "manufacturer",
            "manufacturers",
            "manufacturing",
            "manufactured",
            "manufactures",
            "make",
            "maker",
            "makers",
            "making",
            "produce",
            "producer",
            "producers",
            "producing",
            "production",
            "fabricate",
            "fabricator",
            "fabrication",
            "processing",
            "preserving",
            "casting",
            "forging",
            "distilling",
            "brewing",
            "smelting",
            "milling",
            "spinning",
            "weaving",
            "tanning",
            "factory",
            "factories",
            "manufactory",
        }
    ),
    "wholesale": frozenset(
        {
            "wholesale",
            "wholesaler",
            "wholesalers",
            "wholesaling",
            "distributor",
            "distributors",
            "distribution",
            "distribute",
            "supplier",
            "suppliers",
            "supply",
            "supplying",
            "merchant",
            "merchants",
            "trader",
            "traders",
            "trading",
            "importer",
            "import",
            "exporter",
            "export",
            "reseller",
            "agents",
            "agent",
            "broker",
            "brokers",
            "dealer",
            "dealing",
        }
    ),
    "retail": frozenset(
        {
            "retail",
            "retailer",
            "retailers",
            "retailing",
            "shop",
            "shops",
            "store",
            "stores",
            "seller",
            "sellers",
            "sell",
            "selling",
            "ecommerce",
            "dispensing",
        }
    ),
    "primary": frozenset(
        {
            "growing",
            "raising",
            "farming",
            "farm",
            "farmer",
            "grower",
            "agriculture",
            "agricultural",
            "fishing",
            "fishery",
            "fisheries",
            "hunting",
            "trapping",
            "logging",
            "mining",
            "miner",
            "quarrying",
            "extraction",
            "gathering",
            "silviculture",
            "aquaculture",
            "cultivation",
            "breeding",
        }
    ),
}
ROLE_ORDER: tuple[str, ...] = ("manufacture", "wholesale", "retail", "primary")
ROLE_PRIORITY: dict[str, int] = {"manufacture": 3, "wholesale": 2, "retail": 1, "primary": 0}
# Every role word -- stripped from a description's subject (drives role, not subject).
STRIP_WORDS: frozenset[str] = frozenset().union(*ROLE_WORDS.values())


def detect_icp_roles(text: str) -> list[str]:
    """Roles named in an ICP (or a --role string), in priority order. Empty =>
    no role specified. Handles synonyms ("maker", "wholesaler", "shop",
    "farming") and multi-role ("manufacturer and wholesaler of X")."""
    words = set(text_words(text))
    return [r for r in ROLE_ORDER if words & ROLE_WORDS[r]]


# A "factory" is a manufacturer (so it's in ROLE_WORDS above) but ALSO triggers an
# extra industrial check during enrichment. Kept precise so "plant nursery" /
# "windmill" don't trigger it.
FACTORY_WORDS: frozenset[str] = frozenset({"factory", "factories", "manufactory"})


def is_factory_intent(text: str) -> bool:
    """True when the ICP (or --role) asks specifically for factories, not just any
    manufacturer."""
    return bool(set(text_words(text)) & FACTORY_WORDS)


def sic_role(title: str) -> str | None:
    """The role a SIC title implies (manufacture > wholesale > retail >
    primary), or None for role-less titles ("Repair of ...", "... activities")."""
    words = set(text_words(title))
    for r in ROLE_ORDER:
        if words & ROLE_WORDS[r]:
            return r
    return None


@dataclass
class SicMatch:
    code: str
    description: str
    score: float
    matched_terms: list[str]  # ICP/expansion terms (original spelling) that hit
    role: str | None = None


@dataclass
class MatchResult:
    matches: list[SicMatch]
    status: str  # "ok" | "relaxed" | "generic" | "empty"
    signal_terms: list[str]  # the non-filler ICP subject signal we matched on
    roles: list[str] = field(default_factory=list)  # roles applied (empty = none)
    mode: str = "lexical"  # index retrieval that ran: lexical (BM25) | hybrid (BM25+embeddings)

    @property
    def ok(self) -> bool:
        return bool(self.matches)


def clean_sic_description(desc: str) -> set[str]:
    """Reduce a SIC description to its set of industry-signal stems (subject
    only). Drops filler, role words, <=2-char tokens, pure digits, and the term
    excluded by an "except" clause; stems survivors so they collapse with ICP
    stems (sawmilling ~ sawmill)."""
    out: set[str] = set()
    skip_next = False
    for w in text_words(desc):
        if skip_next:  # the noun excluded by "except"
            skip_next = False
            continue
        if w == "except":
            skip_next = True
            continue
        if len(w) <= 2 or w.isdigit() or w in SIC_FILLER or w in STRIP_WORDS:
            continue  # role words drive role, not subject
        out.add(stem(w))
    return out


# --- cleaned-SIC cache (the 716 descriptions are cleaned once per process) ---

_CLEANED: list[tuple[str, str, set[str], str | None]] | None = None


def load_sic_codes() -> list[tuple[str, str]]:
    """All (code, description) pairs. One seam for callers/tests to monkeypatch."""
    return SIC_CODES


def _cleaned_sics() -> list[tuple[str, str, set[str], str | None]]:
    global _CLEANED
    if _CLEANED is None:
        _CLEANED = [(c, d, clean_sic_description(d), sic_role(d)) for c, d in load_sic_codes()]
    return _CLEANED


def reset_cache() -> None:
    """Clear the cleaned-SIC cache (tests monkeypatching load_sic_codes)."""
    global _CLEANED
    _CLEANED = None


# --- ICP term construction & scoring ---


def _term_weights(profile: icp_phrases.IcpProfile, expansion: set[str] | None) -> dict[str, float]:
    """Subject match terms -> weight: ICP core/qualifier tokens 1.0, their
    SIC-grounded category members (food->meat/dairy/...) 1.0, expansion synonyms
    0.5. Role words are excluded (they drive role, not subject)."""
    weights: dict[str, float] = {}
    subjects: list[str] = []
    for tok in profile.core_tokens:
        t = tok.lower()
        if t not in STRIP_WORDS:
            weights[t] = 1.0
            subjects.append(t)
    for tok in profile.qualifier_tokens:
        t = tok.lower()
        if t not in STRIP_WORDS:
            weights.setdefault(t, 1.0)
            subjects.append(t)
    for t in subjects:  # category hyponyms grounded in SIC names: food -> meat...
        for member in sic_categories.category_members(t):
            weights.setdefault(member.lower(), CATEGORY_WEIGHT)
    for term in expansion or set():
        t = term.lower().strip()
        if t and t not in weights and t not in STRIP_WORDS:
            weights[t] = 0.5
    return weights


def _core_signal(profile: icp_phrases.IcpProfile) -> list[str]:
    """ICP core/qualifier tokens carrying real subject signal -- not filler, not
    generic ('companies'), not a role word ('manufacturing'). Empty => generic
    ICP (no subject to search on)."""
    sig: list[str] = []
    for tok in list(profile.core_tokens) + list(profile.qualifier_tokens):
        t = tok.lower()
        if len(t) <= 2 or t in SIC_FILLER or t in GENERIC_ICP_TERMS:
            continue
        if t in STRIP_WORDS:
            continue
        sig.append(t)
    return sig


def _score_sic(
    stems: set[str], stem_to_terms: dict[str, list[str]], weights: dict[str, float]
) -> tuple[float, list[str]]:
    """Score one SIC's subject stems: a term hits when its stem is in the SIC
    stems or (>=4 chars) is a literal substring of the joined stems -- the same
    primitive as discovery._icp_match. Each hit stem credited once at its max
    term weight so synonym clusters don't pile up points."""
    if not stems:
        return 0.0, []
    joined = " ".join(stems)
    score = 0.0
    matched: list[str] = []
    for st, terms in stem_to_terms.items():
        if not (st in stems or (len(st) >= 4 and st in joined)):
            continue
        score += max(weights[t] for t in terms)
        matched.extend(terms)
    return score, sorted(set(matched))


def match_icp_to_sics(
    icp: str,
    expansion: set[str] | None = None,
    *,
    roles: list[str] | None = None,
    max_sics: int = 5,
    min_score: float = 1.0,
) -> MatchResult:
    """Rank SIC codes against the ICP subject, then apply the role dimension.

    `roles`: the business role(s) to target (manufacture/wholesale/retail). If
    given, keep only SICs of those roles (plus role-less ones) and rank role
    matches first. If empty/None, keep all and rank manufacture > wholesale >
    retail (the user's requested default).

    status: "ok" (subject >= min_score), "relaxed" (best positive overlap),
    "low_confidence" (top-1 too weak: ask for --sic), "generic" (no subject
    signal -- narrow it), or "empty". Subject = SIC-title overlap + ONS index BM25.
    """
    profile = icp_phrases.parse_icp(icp)
    signal = _core_signal(profile)
    weights = _term_weights(profile, expansion)

    stem_to_terms: dict[str, list[str]] = {}
    for term in weights:
        stem_to_terms.setdefault(stem(term), []).append(term)

    reqset = set(roles or [])
    scored: list[tuple] = []  # (rank score, matched, code, desc, role, subject score)
    index, mode = index_scores(icp, signal, SIC_FILLER | STRIP_WORDS)  # ONS index, 0..1 per code
    for code, desc, stems, role in _cleaned_sics():
        sc, matched = _score_sic(stems, stem_to_terms, weights)
        sc += BM25_WEIGHT * index.get(code, 0.0)
        if sc <= 0:
            continue
        if reqset and role is not None and role not in reqset:
            continue  # role specified -> drop other explicit roles (the food-retail bug)
        scored.append((sc + role_bonus(role, reqset, ROLE_PRIORITY), matched, code, desc, role, sc))
    scored.sort(key=lambda x: (-x[0], x[2]))  # subject + role weight; ties by code

    def _mk(x):
        return SicMatch(code=x[2], description=x[3], score=x[0], matched_terms=x[1], role=x[4])

    strict = [_mk(x) for x in scored if x[5] >= min_score][:max_sics]  # role can't lift a SIC in
    chosen = strict if strict else [_mk(x) for x in scored][:max_sics]

    status = match_status(signal, strict, chosen)
    return MatchResult(chosen, status, signal, roles=list(roles or []), mode=mode)


def matches_for_codes(codes: list[str]) -> list[SicMatch]:
    """Build SicMatch entries for explicit SIC codes (the --sic override path),
    resolving each code's description + role from the vendored list."""
    lookup = dict(load_sic_codes())
    out: list[SicMatch] = []
    for raw in codes:
        c = raw.strip()
        if c:
            desc = lookup.get(c, "(unknown SIC code)")
            out.append(SicMatch(c, desc, 0.0, [], sic_role(desc)))
    return out
