"""Website crawler for extracting company descriptions.

Strategy:
  1. Fetch HTML with browser User-Agent (most reliable)
  2. Try trafilatura's extractor (best content quality)
  3. If trafilatura returns nothing, fall back to BeautifulSoup
  4. Also try /about page as a secondary source
  5. Clean the result: filter out short/junk lines
"""

import re
import urllib.request

import trafilatura
from bs4 import BeautifulSoup

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Lines that look like UI noise, demo content, or app chrome
_JUNK_PATTERNS = re.compile(
    r"^("
    r"skip to|cookie|accept all|sign up|log ?in|sign ?in|get started|"
    r"free trial|subscribe|download|menu|toggle|©|\d+ min ago|"
    r"just now|yesterday|created the issue|moved from|added the label|"
    r"@\w|fig \d|render |thinking\.\.\.|on it!|kicked off|searching for|"
    r"locating |examining |\$ |commit |pushed |merged |"
    r"activity|triage |codex|todo|in progress|high|low|medium|"
    r"cycle \d|labelscycle|project\b"
    r")",
    re.IGNORECASE,
)


def _fetch_html(url: str) -> str | None:
    """Download HTML with a real browser User-Agent."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def _extract_trafilatura(html: str) -> str | None:
    """Try trafilatura extraction with both precision and recall modes."""
    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if text and len(text) > 80:
        return text
    # Retry with recall mode for JS-heavy pages
    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        favor_recall=True,
    )
    return text if text and len(text) > 80 else None


def _extract_meta(html: str) -> str | None:
    """Extract meta description and og:description from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    parts = []
    # Page title
    title = soup.find("title")
    if title and title.string:
        parts.append(title.string.strip())
    # Meta descriptions
    for attr in [{"name": "description"}, {"property": "og:description"}]:
        tag = soup.find("meta", attrs=attr)
        if tag and tag.get("content", "").strip():
            val = tag["content"].strip()
            if val not in parts:
                parts.append(val)
    return "\n".join(parts) if parts else None


def _extract_bs4(html: str) -> str:
    """Text extraction via BeautifulSoup (fallback)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "noscript", "svg", "iframe", "form"]):
        tag.decompose()

    # Prefer main/article content if present
    main = soup.find("main") or soup.find("article") or soup.find(role="main")
    target = main if main else soup

    lines = [l for l in target.get_text(separator="\n", strip=True).splitlines()
             if l.strip()]
    return "\n".join(lines)


_TIMESTAMP_RE = re.compile(r"\d+\s*min ago|just now|yesterday|· \d+", re.IGNORECASE)


def _clean_text(text: str) -> str:
    """Filter out UI junk, very short lines, and duplicates."""
    seen = set()
    cleaned = []
    for line in text.splitlines():
        line = line.strip()
        if len(line) < 15:
            continue
        if _JUNK_PATTERNS.match(line):
            continue
        if _TIMESTAMP_RE.search(line):
            continue
        lower = line.lower()
        if lower in seen:
            continue
        seen.add(lower)
        cleaned.append(line)
    return "\n".join(cleaned)


def _try_extract(url: str) -> str | None:
    """Fetch a single URL and extract text."""
    # Try trafilatura's fetcher first (handles encoding well)
    html = trafilatura.fetch_url(url)

    # Fall back to browser UA fetch
    if not html:
        html = _fetch_html(url)
        if not html:
            return None

    # Grab meta descriptions (always useful as a prefix)
    meta = _extract_meta(html)

    # Try trafilatura extractor
    text = _extract_trafilatura(html)

    # Fall back to BeautifulSoup
    if not text:
        text = _extract_bs4(html)

    if not text or not text.strip():
        return meta

    # Prepend meta if we have it (gives clean summary before body text)
    if meta:
        text = meta + "\n\n" + text

    return text


def crawl_website(url: str, max_chars: int = 3000) -> str | None:
    """Fetch and extract main text content from a URL.

    Tries the main URL first, then /about as a supplement.
    Returns cleaned text trimmed to max_chars, or None on failure.
    """
    if not url or not url.strip():
        return None

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        text = _try_extract(url)

        # Also try /about for richer company description
        base = url.rstrip("/")
        about_text = _try_extract(base + "/about")
        if about_text:
            text = (text + "\n" + about_text) if text else about_text

        if not text:
            return None

        text = _clean_text(text)
        if not text:
            return None

        return text[:max_chars].strip()

    except Exception:
        return None
