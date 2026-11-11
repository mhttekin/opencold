from __future__ import annotations

from opencold.discovery_judge import (
    _country_matches,
)


def _classify_company(
    row: dict, icp_evidence: bool, region_conflict: bool, llm: dict | None
) -> tuple[str, str]:
    """Combine deterministic evidence with the (optional) LLM verdict.

    Authority split: deterministic signals own REGION (ccTLD/phone/address are hard
    facts the model can't override); the LLM owns INDUSTRY semantics. The model
    deferring ("unknown") never rejects — we fall back to deterministic. A foreign
    domicile or a government site is rejected; a B2B marketplace/directory is routed to
    'review' (never verified). Disagreements land in 'review'. Returns (confidence,
    reason).
    """
    llm = llm or {}
    llm_match = llm.get("match", "unknown")

    if region_conflict:
        return "rejected", "region_conflict"
    if row.get("_is_government"):
        return "rejected", "government_site"
    if llm_match == "no":
        detail = llm.get("industry") or llm.get("country") or "different company"
        return "rejected", f"llm_mismatch:{detail}"
    if row.get("_is_aggregator"):
        return "review", "marketplace_directory"

    industry_ok = icp_evidence or llm_match == "yes"
    region_ok = bool(row.get("_region_anchor")) or _country_matches(
        row.get("country", ""), llm.get("country", "")
    )

    if industry_ok and region_ok:
        suffix = "+llm" if llm_match == "yes" else ""
        return "verified", f"icp+region_confirmed{suffix}"
    if not industry_ok:
        return "review", "icp_unconfirmed"
    return "review", "region_unconfirmed"
