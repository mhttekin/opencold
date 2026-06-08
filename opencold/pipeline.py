"""Headless draft-generation pipeline shared by the CLI and the HTTP API.

This module is intentionally side-effect free: it never reads disk config,
prompts the user, prints, writes files, or sends email. The CLI (`cli.do_run`)
and the FastAPI server both call :func:`generate_drafts` with already-resolved
inputs and receive structured results back.

Progress is reported through an optional callback that receives plain dicts
(never anything containing secrets), so callers can render terminal output or
update an async job record without this module knowing about either.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional

from opencold import crawler, discovery, enricher, generator, quality, verifier
from opencold.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    build_template_prompt,
)

# A progress event is a small dict, e.g.
#   {"phase": "resolve|verify|enrich|generate|done",
#    "current": int, "total": int, "message": str}
ProgressCallback = Callable[[dict], None]


# ── Pure helpers (mirrors of the cli underscore-helpers, kept here so the
#    pipeline has no dependency on cli.py and avoids a circular import) ────────


def display_name(row: dict) -> str:
    """A row's recipient name — 'name' column, or legacy first/last combined."""
    name = (row.get("name") or "").strip()
    if name:
        return name
    first = (row.get("first_name") or "").strip()
    last = (row.get("last_name") or "").strip()
    return f"{first} {last}".strip()


def normalize_name_columns(rows: list[dict]) -> list[dict]:
    """Ensure every row has a 'name' key (combining legacy first/last if needed)."""
    for row in rows:
        if not (row.get("name") or "").strip():
            combined = display_name(row)
            if combined:
                row["name"] = combined
    return rows


def is_enriched(rows: list[dict]) -> bool:
    return bool(rows and "personalization_facts" in rows[0])


def clamp_workers(workers: int) -> int:
    """Keep parallelism useful without hammering websites or LLM APIs."""
    return max(1, min(int(workers or 1), 8))


def has_enough_context(campaign: dict) -> bool:
    return bool(campaign.get("description") and campaign.get("pitch"))


# ── Result type ──────────────────────────────────────────────────────────────


@dataclass
class PipelineResult:
    rows: list[dict]            # result rows: input cols + generated_* + quality_warnings
    success_count: int
    total_count: int
    dropped: list[dict] = field(default_factory=list)  # [{"row": {...}, "reason": "..."}]


def _emit(progress: Optional[ProgressCallback], **event) -> None:
    if progress is None:
        return
    try:
        progress(event)
    except Exception:
        # Progress reporting must never break the pipeline.
        pass


def _provider_config(provider: dict) -> dict:
    """Map an API/CLI provider dict to the shape ``generator`` expects."""
    cfg = {
        "type": provider.get("type", "anthropic"),
        "api_key": provider.get("api_key", ""),
        "default_model": provider.get("model") or "",
    }
    if provider.get("base_url"):
        cfg["base_url"] = provider["base_url"]
    if provider.get("max_tokens"):
        cfg["max_tokens"] = provider["max_tokens"]
    return cfg


# ── Pipeline stages ──────────────────────────────────────────────────────────


def _resolve_missing_websites(
    rows: list[dict], workers: int, progress: Optional[ProgressCallback]
) -> list[dict]:
    """Fill missing 'website' values by searching the company name (free backends)."""
    has_col = bool(rows) and "website" in rows[0]
    targets = [
        r
        for r in rows
        if r.get("company", "").strip()
        and not (r.get("website", "").strip() if has_col else "")
    ]
    if not targets:
        return rows

    # Keep the column consistent for everything downstream.
    for r in rows:
        r.setdefault("website", "")

    by_company: dict[str, list[dict]] = {}
    for r in targets:
        by_company.setdefault(r["company"].strip(), []).append(r)

    total = len(by_company)
    worker_count = max(1, min(clamp_workers(workers), total))
    _emit(progress, phase="resolve", current=0, total=total,
          message=f"Resolving {len(targets)} missing website(s) by company name")

    resolved: dict[str, str] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_company = {
            executor.submit(discovery.resolve_company_website, company): company
            for company in by_company
        }
        for future in as_completed(future_to_company):
            company = future_to_company[future]
            try:
                url = future.result()
            except Exception:
                url = None
            if url:
                resolved[company] = url
            done += 1
            _emit(progress, phase="resolve", current=done, total=total,
                  message=f"{company} → {url or 'no match'}")

    for company, company_rows in by_company.items():
        url = resolved.get(company)
        if url:
            for r in company_rows:
                r["website"] = url
    return rows


def _verify_rows(
    rows: list[dict], drop_invalid: bool, progress: Optional[ProgressCallback]
) -> tuple[list[dict], list[dict]]:
    """Verify emails (format + MX). Drops invalid rows only when ``drop_invalid``."""
    total = len(rows)
    _emit(progress, phase="verify", current=0, total=total,
          message=f"Verifying {total} email(s)")

    kept: list[dict] = []
    dropped: list[dict] = []
    for i, row in enumerate(rows, start=1):
        email = (row.get("email") or "").strip()
        result = verifier.verify_email(email) if email else {"valid": False, "reason": "empty"}
        if result["valid"] or not drop_invalid:
            kept.append(row)
        else:
            dropped.append({"row": row, "reason": result["reason"]})
        _emit(progress, phase="verify", current=i, total=total,
              message=f"{email or '(no email)'}: {'valid' if result['valid'] else result['reason']}")
    return kept, dropped


def _enrich_rows(
    rows: list[dict], workers: int, progress: Optional[ProgressCallback], max_pages: int = 4
) -> list[dict]:
    """Crawl each unique website once and attach grounded personalization facts."""
    workers = clamp_workers(workers)

    websites: list[str] = []
    seen: set[str] = set()
    for row in rows:
        website = enricher.normalize_url(row.get("website", ""))
        if website and website not in seen:
            seen.add(website)
            websites.append(website)

    website_results: dict[str, dict] = {}
    if websites:
        worker_count = max(1, min(workers, len(websites)))
        _emit(progress, phase="enrich", current=0, total=len(websites),
              message=f"Crawling {len(websites)} unique website(s)")
        done = 0
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_website = {
                executor.submit(enricher.enrich_website, website, max_pages): website
                for website in websites
            }
            for future in as_completed(future_to_website):
                website = future_to_website[future]
                try:
                    website_results[website] = future.result()
                except Exception as e:
                    website_results[website] = {
                        "website_status": "fetch_failed",
                        "company_summary": "",
                        "personalization_facts": "",
                        "source_urls": "",
                        "personalization_score": "0",
                        "quality_warnings": f"website_fetch_failed{enricher.FACT_SEPARATOR}{type(e).__name__}",
                        "enrichment_json": "{}",
                    }
                done += 1
                _emit(progress, phase="enrich", current=done, total=len(websites),
                      message=f"{website}: {website_results[website].get('website_status', '')}")

    enriched: list[dict] = []
    for row in rows:
        enriched_row = dict(row)
        email = row.get("email", "")
        if email.strip():
            email_result = verifier.verify_email(email)
            enriched_row["verification_status"] = (
                "valid" if email_result["valid"] else f"invalid: {email_result['reason']}"
            )
        else:
            enriched_row["verification_status"] = "missing"
        website = enricher.normalize_url(row.get("website", ""))
        enriched_row.update(
            website_results.get(website) or enricher.enrich_website("", max_pages=max_pages)
        )
        enriched.append(enriched_row)
    return enriched


def _generate_all(
    rows: list[dict],
    *,
    sys_prompt: str,
    use_flags: bool,
    template: Optional[str],
    identity: dict,
    profile: dict,
    campaign: dict,
    provider_config: dict,
    effective_model: str,
    max_tokens: Optional[int],
    sender_name: str,
    has_websites: bool,
    workers: int,
    delay: float,
    progress: Optional[ProgressCallback],
) -> list[dict]:
    """Generate one draft per row in parallel batches. Mirrors cli.do_run's core."""
    results: list[dict] = []
    total = len(rows)
    batch_size = workers

    def _build_prompt(row: dict, website_text: Optional[str]) -> str:
        if use_flags and template:
            return template.format(**row)
        elif use_flags:
            return (
                f"Write a cold outreach email to {display_name(row)} "
                f"at {row.get('company', '')}. Their email is {row.get('email', '')}."
            )
        elif campaign and has_enough_context(campaign):
            return build_user_prompt(
                row,
                identity,
                profile,
                campaign,
                website_text,
                personalization_facts=row.get("personalization_facts", ""),
            )
        else:
            return build_template_prompt(row, identity, profile)

    def _generate_one(row: dict) -> dict:
        website_text = None
        if has_websites and not row.get("personalization_facts"):
            website_text = crawler.crawl_website(row.get("website", ""))
        user_prompt = _build_prompt(row, website_text)
        result = generator.generate_with_retry(
            provider_config, sys_prompt, user_prompt, effective_model, max_tokens
        )
        body = result["body"]
        if sender_name:
            body = f"{body}\n\n{sender_name}"
        return {"subject": result["subject"], "body": body}

    completed = 0
    for batch_start in range(0, total, batch_size):
        batch_indices = list(range(batch_start, min(batch_start + batch_size, total)))

        batch_results: dict[int, dict | Exception] = {}
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            future_to_idx = {
                executor.submit(_generate_one, rows[idx]): idx for idx in batch_indices
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    batch_results[idx] = future.result()
                except Exception as e:  # noqa: BLE001 — surfaced per-row, not fatal
                    batch_results[idx] = e

        for idx in batch_indices:
            row = rows[idx]
            result = batch_results[idx]
            completed += 1
            if isinstance(result, Exception):
                warnings = quality.merge_warnings(
                    row.get("quality_warnings", ""), ["generation_failed"]
                )
                results.append({
                    **row,
                    "quality_warnings": warnings,
                    "generated_subject": "",
                    "generated_email": f"ERROR: {result}",
                })
                _emit(progress, phase="generate", current=completed, total=total,
                      message=f"[{completed}/{total}] {display_name(row)} — failed")
            else:
                draft_warnings = quality.evaluate_draft(
                    result["subject"], result["body"], row.get("personalization_facts", "")
                )
                warnings = quality.merge_warnings(row.get("quality_warnings", ""), draft_warnings)
                results.append({
                    **row,
                    "quality_warnings": warnings,
                    "generated_subject": result["subject"],
                    "generated_email": result["body"],
                })
                _emit(progress, phase="generate", current=completed, total=total,
                      message=f"[{completed}/{total}] {display_name(row)} — done")

        # Delay between batches, not between individual requests.
        if batch_start + batch_size < total:
            time.sleep(delay)

    return results


# ── Public entry point ───────────────────────────────────────────────────────


def generate_drafts(
    leads: list[dict],
    campaign: dict,
    identity: dict,
    profile: dict,
    provider: dict,
    *,
    workers: int = 5,
    delay: float = 0.5,
    template: Optional[str] = None,
    system_prompt: Optional[str] = None,
    max_tokens: Optional[int] = None,
    do_resolve_websites: bool = True,
    do_enrich: bool = True,
    do_verify: bool = True,
    drop_invalid: bool = False,
    progress: Optional[ProgressCallback] = None,
) -> PipelineResult:
    """Generate cold-email drafts for ``leads`` — headless, no I/O, no prompts.

    Args:
        leads: parsed CSV rows; each should carry at least ``name``/``company``/``email``.
        campaign: ``{title, description, pitch}`` (empty dict falls back to a template prompt).
        identity: ``{name, email}`` of the sender.
        profile: ``{company, role, bio, pitch}`` of the sender.
        provider: ``{type, api_key, model, base_url?, max_tokens?}`` — used per request,
            never read from or written to disk.
        do_resolve_websites/do_enrich/do_verify: toggle each preprocessing stage.
        drop_invalid: when True, rows whose email fails verification are dropped.
        progress: optional callback receiving small, secret-free progress dicts.

    Returns a :class:`PipelineResult` with result rows (input columns plus
    ``generated_subject``/``generated_email``/``quality_warnings``).
    """
    campaign = campaign or {}
    identity = identity or {}
    profile = profile or {}
    workers = clamp_workers(workers)
    dropped: list[dict] = []

    # Defensive copy so callers never see their input dicts mutated underneath them.
    rows = [dict(r) for r in leads]
    rows = normalize_name_columns(rows)
    for r in rows:
        r.setdefault("email", "")
        r.setdefault("company", "")
    if not rows:
        return PipelineResult([], 0, 0, dropped)

    enriched_input = is_enriched(rows)

    if do_resolve_websites and not enriched_input:
        rows = _resolve_missing_websites(rows, workers, progress)

    if do_verify:
        rows, dropped = _verify_rows(rows, drop_invalid, progress)
        if not rows:
            return PipelineResult([], 0, 0, dropped)

    has_websites = bool(rows) and "website" in rows[0]
    if do_enrich and has_websites and not is_enriched(rows):
        rows = _enrich_rows(rows, workers, progress)
        has_websites = "website" in rows[0]

    use_flags = system_prompt is not None or template is not None
    sys_prompt = system_prompt or SYSTEM_PROMPT
    provider_config = _provider_config(provider)
    effective_model = (
        provider.get("model") or provider_config.get("default_model") or generator.DEFAULT_MODEL
    )
    sender_name = identity.get("name", "")

    total = len(rows)
    _emit(progress, phase="generate", current=0, total=total,
          message=f"Generating {total} draft(s) with {effective_model}")

    results = _generate_all(
        rows,
        sys_prompt=sys_prompt,
        use_flags=use_flags,
        template=template,
        identity=identity,
        profile=profile,
        campaign=campaign,
        provider_config=provider_config,
        effective_model=effective_model,
        max_tokens=max_tokens,
        sender_name=sender_name,
        has_websites=has_websites,
        workers=workers,
        delay=delay,
        progress=progress,
    )

    success = sum(1 for r in results if not r["generated_email"].startswith("ERROR:"))
    _emit(progress, phase="done", current=total, total=total,
          message=f"Done — {success}/{total} generated")
    return PipelineResult(results, success, total, dropped)
