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
