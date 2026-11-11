from __future__ import annotations

import json
import re

# ---------------------------------------------------------------------------
# Front-end: candidate companies from LLM seed + search (sources optional)
# ---------------------------------------------------------------------------


def _resolve_llm_provider() -> dict | None:
    """Resolve an LLM provider config for discovery seeding, or None if unavailable.

    Mirrors the resolution order used by the email run path: default provider ->
    its config -> any usable LLM provider -> legacy anthropic key. Returns None
    when nothing is set up so callers degrade gracefully to search-only discovery.
    """
    try:
        from opencold import config
        from opencold import generator as _gen
    except Exception:
        return None
    try:
        providers = config.get_providers()
        name = config.get_default_provider_name()
        prov = providers.get(name) if name else None
        if prov and prov.get("type") in ("anthropic", "openai", "proxy") and prov.get("api_key"):
            return prov
        for candidate in providers.values():
            if candidate.get("type") in ("anthropic", "openai", "proxy") and candidate.get(
                "api_key"
            ):
                return candidate
        legacy = config.get_api_key("anthropic")
        if legacy:
            return {"type": "anthropic", "api_key": legacy, "default_model": _gen.DEFAULT_MODEL}
    except Exception:
        return None
    return None


_SEED_SYSTEM = (
    "You are a B2B market researcher. You output ONLY compact JSON, no prose, no "
    "markdown code fences. You never invent fake companies; if unsure, return fewer."
)


def _build_seed_prompt(icp: str, region: str, count: int, related: set[str] | None = None) -> str:
    hint = ""
    if related:
        hint = (
            f"Related terms (same industry, treat as in-scope): {', '.join(sorted(related)[:8])}\n"
        )
    return (
        f"Target profile: {icp}\n"
        f"Region/country: {region}\n"
        f"{hint}\n"
        f"Return up to {count} real, currently-operating companies that match the "
        f"target profile and are based in or serve that region. Prefer local small "
        f"and mid-size companies over global multinationals.\n"
        f"Also list authoritative local indexes where many more such companies are "
        f"registered (industry regulator, licensing body, trade association, chamber "
        f"of commerce) — these are used as extra search hints.\n\n"
        f'Output JSON exactly: {{"companies": ["Company Name", ...], '
        f'"local_directories": ["regulator/association name or url", ...]}}'
    )


def _parse_json_object(text: str) -> dict:
    """Best-effort parse of a JSON object from an LLM response (tolerates fences/prose)."""
    if not text:
        return {}
    cleaned = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
    return {}


def seed_companies_via_llm(
    icp: str,
    region: str,
    count: int = 30,
    provider_config: dict | None = None,
    related: set[str] | None = None,
) -> dict:
    """Ask an LLM for known companies + local directories for (ICP, region).

    Returns {"companies": [...], "local_directories": [...]}. On any failure or
    when no provider is available, returns empty lists so discovery degrades to
    search-only.
    """
    prov = provider_config or _resolve_llm_provider()
    if not prov:
        return {"companies": [], "local_directories": []}
    try:
        from opencold import generator as _gen

        raw = _gen.complete(
            prov, _SEED_SYSTEM, _build_seed_prompt(icp, region, count, related), max_tokens=1024
        )
    except Exception:
        return {"companies": [], "local_directories": []}
    data = _parse_json_object(raw)
    companies = [c.strip() for c in data.get("companies", []) if isinstance(c, str) and c.strip()]
    directories = [
        d.strip() for d in data.get("local_directories", []) if isinstance(d, str) and d.strip()
    ]
    seen: set[str] = set()
    uniq: list[str] = []
    for c in companies:
        key = c.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return {"companies": uniq[:count], "local_directories": directories[:10]}
