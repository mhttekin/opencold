"""Ranking weights for SIC candidates (kept out of sic_match to keep it small).

Role is a WEIGHT added to the subject score, not the primary sort key. Before,
any manufacture-role SIC outranked every role-less one regardless of subject
fit, so "sawmilling" ranked "veneer sheets" (1.0, manufacture) above
"sawmilling and planing" (2.0, no role).
"""

from __future__ import annotations

# A requested role adds 0.5 -- the weight of one expansion-synonym hit. That settles
# near-ties between equally relevant SICs, but can never lift a SIC above one that
# matches one more core ICP token (1.0): subject fit stays the dominant signal.
ROLE_MATCH_WEIGHT = 0.5
# With no role requested, keep the stated default preference manufacture >
# wholesale > retail as a tie-breaker only: 0.1 per priority step (max 0.3), well
# below any single subject-term difference.
ROLE_DEFAULT_STEP = 0.1


def role_bonus(role: str | None, requested: set[str], priority: dict[str, int]) -> float:
    if requested:
        return ROLE_MATCH_WEIGHT if role in requested else 0.0
    return ROLE_DEFAULT_STEP * priority.get(role or "", 0)


# ONS index (BM25) weight. sic_index scores a code 0..1 = the idf-weighted share of
# the ICP its best ONS activity phrase covers. A phrase covering the whole ICP is
# worth two core-term hits in a SIC title: the index is ONS's own mapping of ~16k
# specific activities to codes, so it should lead, while title hits still add up.
BM25_WEIGHT = 2.0

# Below this top-1 score smearch stops, shows the top-5 and asks for --sic. 2.0 means
# "some source fully supports the ICP": two core terms in the SIC title, an ONS
# activity phrase covering the whole ICP (1.0 x BM25_WEIGHT), or half of each. Below
# it the best code rests on one partial signal (e.g. a lone word like "craft" or
# "panel"), which on varied probe ICPs was wrong far more often than right.
SIC_CONFIDENCE_MIN = 2.0


def match_status(signal: list[str], strict: list, chosen: list) -> str:
    """generic (no subject signal) | ok | relaxed (only sub-min_score overlap) |
    low_confidence (top-1 under SIC_CONFIDENCE_MIN) | empty."""
    if not signal:
        return "generic"
    if not chosen:
        return "empty"
    if chosen[0].score < SIC_CONFIDENCE_MIN:
        return "low_confidence"
    return "ok" if strict else "relaxed"


def low_confidence_message(match) -> str:
    """CLI stop message for a low_confidence match ("" otherwise)."""
    if match.status != "low_confidence":
        return ""
    top = match.matches[0].score
    return f"Low SIC confidence (top score {top:.2f} < {SIC_CONFIDENCE_MIN:g}). Re-run with --sic CODES."
