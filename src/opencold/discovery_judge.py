from __future__ import annotations

from opencold.discovery_domains import (
    normalize_domain,
)
from opencold.discovery_region import (
    _resolve_region_key,
)
from opencold.discovery_seed import (
    _parse_json_object,
)

# ---------------------------------------------------------------------------
# Verification: LLM judge (grounded) + deterministic gate
# ---------------------------------------------------------------------------


def _country_matches(region: str, country: str) -> bool:
    """True when a detected country resolves to the same canonical region."""
    if not country:
        return False
    rk = _resolve_region_key(region)
    ck = _resolve_region_key(country)
    return bool(rk and ck and rk == ck)


_JUDGE_SYSTEM = (
    "You verify whether companies match a target profile and region, using ONLY "
    "the provided website summary as evidence. You output compact JSON, no prose, "
    "no markdown fences. If a summary does not clearly establish a company's "
    'industry or country, you answer "unknown" — you never guess from the name.'
)


def _build_judge_prompt(items: list[dict], icp: str, region: str) -> str:
    lines = [
        f"Target industry/profile: {icp}",
        f"Target region: {region}",
        "",
        "For each company, judge from its OWN website summary whether it matches the "
        "target industry AND is based in or serves the target region.",
        'Reply JSON: {"results":[{"i":0,"match":"yes|no|unknown","industry":"...",'
        '"country":"...","evidence":"<short quote from the summary>"}]}',
        "Rules: base every field ONLY on the summary text. If the summary is too "
        'thin to tell, use "unknown" (do not guess). Quote real words from the '
        "summary as evidence.",
        "",
        "Companies:",
    ]
    for it in items:
        summary = (it.get("summary") or "")[:500].replace("\n", " ")
        lines.append(f'[{it["i"]}] name="{it["name"]}" site={it["domain"]} summary="{summary}"')
    return "\n".join(lines)


def judge_companies(rows: list[dict], icp: str, region: str, provider_config: dict) -> dict:
    """Single batched LLM verdict per company, grounded in crawled summaries.

    Returns {row_index: {"match": yes|no|unknown, "industry", "country", "evidence"}}.
    On any failure returns {} so the caller falls back to deterministic signals.
    """
    items = []
    for idx, row in enumerate(rows):
        summary = " ".join(
            [
                row.get("company_summary", ""),
                row.get("personalization_facts", ""),
            ]
        ).strip()
        items.append(
            {
                "i": idx,
                "name": row.get("company", ""),
                "domain": normalize_domain(row.get("website", "")),
                "summary": summary,
            }
        )
    if not items:
        return {}
    try:
        from opencold import generator as _gen

        raw = _gen.complete(
            provider_config, _JUDGE_SYSTEM, _build_judge_prompt(items, icp, region), max_tokens=1500
        )
    except Exception:
        return {}
    data = _parse_json_object(raw)
    out: dict = {}
    for res in data.get("results", []):
        if isinstance(res, dict) and isinstance(res.get("i"), int):
            out[res["i"]] = {
                "match": str(res.get("match", "unknown")).lower().strip(),
                "industry": str(res.get("industry", "")),
                "country": str(res.get("country", "")),
                "evidence": str(res.get("evidence", "")),
            }
    return out
