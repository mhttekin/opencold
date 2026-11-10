"""Lead enrichment from company websites.

The enrichment layer keeps personalization grounded in source text. It uses
deterministic extraction and scoring by default so preparing leads stays cheap,
fast, and testable.
"""

from __future__ import annotations

import csv
import json
import re
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse
import urllib.request

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

from opencold import crawler, verifier

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

DEFAULT_PATHS = (
    "",
    "/about",
    "/customers",
    "/case-studies",
    "/blog",
    "/careers",
    "/pricing",
)

FACT_SEPARATOR = " | "
FETCH_TIMEOUT = 6.0

_FACT_VERBS = re.compile(
    r"\b("
    r"builds?|helps?|offers?|provides?|enables?|automates?|connects?|"
    r"supports?|serves?|works with|integrates?|protects?|manages?|"
    r"tracks?|uses?|creates?|delivers?|speciali[sz]es"
    r")\b",
    re.IGNORECASE,
)
_NOISE = re.compile(
    r"\b(cookie|privacy policy|terms of service|all rights reserved|"
    r"sign up|log in|subscribe|newsletter|book a demo|get started|"
    r"upgrade to|use .* for free|start for free|try for free|"
    r"find out .*cost|pricing|unlimited issues)\b",
    re.IGNORECASE,
)
_SPACE = re.compile(r"\s+")
_REPEATED_PHRASE = re.compile(r"\b(.{18,80}?)\s+\1\b", re.IGNORECASE)


@dataclass
class PageContent:
    url: str
    title: str = ""
    description: str = ""
    headings: list[str] | None = None
    jsonld: list[str] | None = None
    text: str = ""
    status: str = "ok"

    def source_texts(self) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        if self.description:
            items.append(("meta", self.description))
        if self.title:
            items.append(("title", self.title))
        for heading in self.headings or []:
            items.append(("heading", heading))
        for item in self.jsonld or []:
            items.append(("jsonld", item))
        for line in self.text.splitlines():
            items.append(("body", line))
        return items


@dataclass
class Fact:
    text: str
    source_url: str
    source_type: str
    confidence: float


def normalize_url(url: str) -> str:
    """Normalize a website value into an absolute URL."""
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        return ""
    return parsed.geturl().rstrip("/")


def _candidate_urls(url: str, max_pages: int) -> list[str]:
    base = normalize_url(url)
    if not base:
        return []
    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    urls = []
    seen = set()
    for path in DEFAULT_PATHS:
        candidate = origin if not path else urljoin(origin, path)
        if candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
        if len(urls) >= max_pages:
            break
    return urls


def _clean_sentence(text: str) -> str:
    text = BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True)
    text = _SPACE.sub(" ", text).strip(" \t\r\n-–—|")
    while _REPEATED_PHRASE.search(text):
        text = _REPEATED_PHRASE.sub(r"\1", text)
    return text


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [_clean_sentence(p) for p in parts if _clean_sentence(p)]


def _extract_structured_html(html: str, url: str) -> PageContent:
    soup = BeautifulSoup(html or "", "html.parser")
    title = _clean_sentence(soup.title.string if soup.title and soup.title.string else "")

    descriptions = []
    for attrs in (
        {"name": "description"},
        {"property": "og:description"},
        {"name": "twitter:description"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            descriptions.append(_clean_sentence(tag["content"]))
    description = next((d for d in descriptions if d), "")

    headings = []
    for tag in soup.find_all(["h1", "h2"], limit=12):
        value = _clean_sentence(tag.get_text(" ", strip=True))
        if value and value.lower() not in {h.lower() for h in headings}:
            headings.append(value)

    jsonld = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}, limit=5):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict):
                continue
            for key in ("description", "slogan", "name"):
                value = _clean_sentence(str(item.get(key, "")))
                if value:
                    jsonld.append(value)

    for tag in soup(["script", "style", "nav", "footer", "header", "form", "svg"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.find(role="main") or soup
    text = crawler._clean_text(main.get_text("\n", strip=True))

    return PageContent(
        url=url,
        title=title,
        description=description,
        headings=headings,
        jsonld=jsonld,
        text=text,
    )


def _fetch_html(url: str, timeout: float = FETCH_TIMEOUT) -> str | None:
    """Fetch HTML with a bounded timeout."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": crawler._UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("content-type", "")
            if "text/html" not in ctype and "application/xhtml" not in ctype:
                return None
            return resp.read(2_000_000).decode("utf-8", errors="replace")
    except Exception:
        return None


def fetch_page(url: str) -> PageContent:
    """Fetch one page and return structured content."""
    html = _fetch_html(url)
    if not html:
        return PageContent(url=url, status="fetch_failed")
    page = _extract_structured_html(html, url)
    if not page.text and not page.description and not page.headings:
        page.status = "empty"
    return page


def crawl_site(url: str, max_pages: int = 5) -> list[PageContent]:
    """Crawl a small fixed set of high-value pages for a company site."""
    pages = []
    for candidate in _candidate_urls(url, max_pages=max_pages):
        page = fetch_page(candidate)
        if page.status == "ok":
            pages.append(page)
    return pages


def _score_fact(text: str, source_type: str, page_index: int) -> float:
    score = 0.25
    if source_type in {"meta", "jsonld"}:
        score += 0.35
    elif source_type == "heading":
        score += 0.25
    if _FACT_VERBS.search(text):
        score += 0.25
    if 45 <= len(text) <= 180:
        score += 0.1
    if page_index == 0:
        score += 0.05
    lower_url_hint = text.lower()
    if "pricing" in lower_url_hint or "free" in lower_url_hint or "upgrade" in lower_url_hint:
        score -= 0.2
    return min(score, 0.95)


def _page_penalty(url: str) -> float:
    path = urlparse(url).path.lower()
    if "pricing" in path:
        return 0.25
    if "careers" in path or "blog" in path:
        return 0.1
    return 0.0


def extract_facts(pages: list[PageContent], max_facts: int = 5) -> list[Fact]:
    """Extract and rank source-grounded company facts."""
    facts: list[Fact] = []
    seen = set()
    for page_index, page in enumerate(pages):
        for source_type, raw_text in page.source_texts():
            for sentence in _split_sentences(raw_text):
                if len(sentence) < 35 or len(sentence) > 240:
                    continue
                if _NOISE.search(sentence):
                    continue
                normalized = sentence.lower()
                if normalized in seen:
                    continue
                seen.add(normalized)
                confidence = max(0.05, _score_fact(sentence, source_type, page_index) - _page_penalty(page.url))
                facts.append(Fact(sentence, page.url, source_type, confidence))

    facts.sort(key=lambda f: f.confidence, reverse=True)
    return facts[:max_facts]


def summarize_facts(facts: list[Fact]) -> str:
    """Create a compact summary from the best available fact."""
    return facts[0].text if facts else ""


def facts_to_text(facts: list[Fact]) -> str:
    return FACT_SEPARATOR.join(f.text for f in facts)


def source_urls(facts: list[Fact]) -> str:
    urls = []
    for fact in facts:
        if fact.source_url not in urls:
            urls.append(fact.source_url)
    return FACT_SEPARATOR.join(urls)


def personalization_score(facts: list[Fact]) -> int:
    if not facts:
        return 0
    avg = sum(f.confidence for f in facts) / len(facts)
    volume_bonus = min(len(facts) * 8, 30)
    return min(100, round(avg * 70 + volume_bonus))


def quality_warnings(facts: list[Fact], pages: list[PageContent]) -> list[str]:
    warnings = []
    if not pages:
        warnings.append("website_fetch_failed")
    if not facts:
        warnings.append("no_grounded_facts")
    elif personalization_score(facts) < 55:
        warnings.append("low_personalization_confidence")
    return warnings


def enrich_website(website: str, max_pages: int = 4) -> dict:
    """Return CSV-safe website enrichment fields."""
    pages = crawl_site(website, max_pages=max_pages) if website else []
    facts = extract_facts(pages)
    warnings = quality_warnings(facts, pages)
    return {
        "website_status": "ok" if pages else ("missing" if not website else "fetch_failed"),
        "company_summary": summarize_facts(facts),
        "personalization_facts": facts_to_text(facts),
        "source_urls": source_urls(facts),
        "personalization_score": str(personalization_score(facts)),
        "quality_warnings": FACT_SEPARATOR.join(warnings),
        "enrichment_json": json.dumps(
            {"facts": [asdict(f) for f in facts], "warnings": warnings},
            ensure_ascii=False,
        ),
    }


def enrich_row(row: dict, max_pages: int = 4) -> dict:
    """Return a CSV-safe enriched lead row."""
    result = dict(row)
    email_result = verifier.verify_email(row.get("email", ""))
    result["verification_status"] = "valid" if email_result["valid"] else f"invalid: {email_result['reason']}"

    result.update(enrich_website(row.get("website", ""), max_pages=max_pages))
    return result


def write_csv(rows: list[dict], path: str) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    dest = open(path, "w", newline="", encoding="utf-8")
    with dest:
        writer = csv.DictWriter(dest, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: str) -> list[dict]:
    with open(Path(path), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
