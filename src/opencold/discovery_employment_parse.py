from __future__ import annotations

import re

from opencold.discovery_data import (
    _EMPLOYMENT_DATE_RE,
    _MOVED_PATTERNS,
    _NOT_EMPLOYED_RE,
    COMPANY_SUFFIXES_RE,
    LINKEDIN_TITLE_RE,
)
from opencold.discovery_person_match import _company_name_matches
from opencold.discovery_person_score import (
    _valid_person_name,
)
from opencold.discovery_search_models import SearchResult


def _parse_linkedin_title(title: str) -> tuple[str, str, str] | None:
    """Parse a LinkedIn profile title into (name, role, company) or None."""
    m = LINKEDIN_TITLE_RE.match(title)
    if not m:
        return None
    name = m.group("name").strip()
    role = m.group("role").strip()
    company = m.group("company").strip()
    if not _valid_person_name(name):
        return None
    return name, role, company


def _company_in_title(title: str, company_lower: str, company_tokens: set[str]) -> bool:
    """Check if company name appears in a search result title."""
    title_lower = title.lower()
    if company_lower in title_lower:
        return True
    if len(company_tokens) > 1:
        found = sum(1 for t in company_tokens if t in title_lower)
        if found >= len(company_tokens) * 0.6:
            return True
    elif company_tokens:
        token = list(company_tokens)[0]
        if re.search(r"\b" + re.escape(token) + r"\b", title_lower):
            return True
    return False


_COMMON_ROLES_RE = re.compile(
    r"(?i:^(?:engineer|developer|designer|manager|director|analyst|consultant|"
    r"scientist|architect|lead|head|chief|vp|president|founder|ceo|cto|cfo|coo|"
    r"intern|associate|coordinator|specialist|strategist|officer|advisor|"
    r"professor|researcher|student|freelanc))",
)


def _extract_linkedin_company_from_title(title: str) -> str:
    """Extract the company name from a LinkedIn-style search result title.

    Handles formats:
      "Name - Role - Company | LinkedIn" → Company
      "Name - Company | LinkedIn" → Company  (if not a common role word)
    """
    parsed = _parse_linkedin_title(title)
    if parsed:
        return parsed[2]  # company field
    # Fallback: split by dashes and look for "... | LinkedIn" at the end
    parts = re.split(r"\s*[-–—]\s*", title)
    if len(parts) >= 2 and "linkedin" in parts[-1].lower():
        # Last part might be "Company | LinkedIn" or just "LinkedIn"
        last = parts[-1].split("|")[0].strip()
        if last.lower() == "linkedin":
            # The company is in the second-to-last part (for 3+ parts)
            if len(parts) >= 3:
                candidate = parts[-2].split("|")[0].strip()
                if not _COMMON_ROLES_RE.match(candidate):
                    return candidate
        elif last and not _COMMON_ROLES_RE.match(last):
            # "Name - Company | LinkedIn" → Company is before the pipe
            return last
    return ""


def _check_employment_dates(text: str, company: str) -> tuple[str, bool] | None:
    """Check for LinkedIn employment date ranges in text.

    Returns (date_range_str, is_current) or None if no dates found.
    """
    company_lower = company.lower()
    # Look for patterns like "Jan 2023 - Present" near the company name
    for m in _EMPLOYMENT_DATE_RE.finditer(text):
        # Check if company name is near this date range (within 200 chars)
        start = max(0, m.start() - 200)
        context = text[start : m.end() + 50].lower()
        if company_lower not in context:
            continue
        end_date = m.group(2).strip()
        date_str = m.group(0)
        is_current = end_date.lower() == "present"
        return date_str, is_current
    return None


def _analyze_engine_results(results: list[SearchResult], company: str) -> dict:
    """Analyze a single engine's results for employment signals.

    Returns a dict with keys: confirms, contradicts, not_employed,
    moved_to, date_info, company_in_title, other_company.
    """
    analysis: dict = {
        "confirms": False,
        "contradicts": False,
        "not_employed": False,
        "moved_to": "",
        "date_info": None,  # (date_str, is_current) or None
        "company_in_title": False,
        "other_company": "",
        "published_dates": [],
    }

    company_lower = COMPANY_SUFFIXES_RE.sub("", company).strip().lower()
    company_tokens = set(company_lower.split())
    combined_text = " ".join(f"{r.title} {r.snippet}" for r in results)

    # Check for not-employed signals
    if _NOT_EMPLOYED_RE.search(combined_text):
        analysis["not_employed"] = True

    # Check for move signals
    match = _MOVED_PATTERNS.search(combined_text)
    if match:
        new_company = (
            match.group("new1")
            or match.group("new2")
            or match.group("new3")
            or match.group("new4")
            or ""
        ).strip()
        if new_company and not _company_name_matches(new_company, company):
            analysis["moved_to"] = new_company

    # Check LinkedIn titles — only process first ~120 chars to avoid DDG's
    # concatenated multi-result garbage titles
    for result in results:
        if "linkedin.com/in" not in result.url:
            continue
        # DDG sometimes concatenates multiple result titles; truncate to first
        title = result.title
        pipe_idx = title.find("| LinkedIn")
        if pipe_idx > 0:
            title = title[: pipe_idx + len("| LinkedIn")]

        if _company_in_title(title, company_lower, company_tokens):
            analysis["company_in_title"] = True
            analysis["confirms"] = True
        else:
            # Extract what company IS in the title
            other = _extract_linkedin_company_from_title(title)
            if other and not _company_name_matches(other, company):
                analysis["other_company"] = other
                analysis["contradicts"] = True

        # Check for employment dates in snippet
        date_info = _check_employment_dates(f"{title} {result.snippet}", company)
        if date_info:
            analysis["date_info"] = date_info

    # Collect published dates for recency comparison
    for result in results:
        if result.published_date:
            analysis["published_dates"].append(result.published_date)

    # Snippet-level confirmation — only if no LinkedIn title signals found
    # (snippets from non-LinkedIn pages like author bios can be misleading)
    if not analysis["confirms"] and not analysis["contradicts"]:
        snippet_text = " ".join(r.snippet for r in results).lower()
        if company_lower in snippet_text:
            analysis["confirms"] = True

    return analysis
