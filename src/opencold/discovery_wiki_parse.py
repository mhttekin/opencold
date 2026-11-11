"""Wikipedia list-page fetch and wikitext name parsing for the wiki channel."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

from opencold.discovery_data import SEARCH_TIMEOUT
from opencold.discovery_domains import _clean_text
from opencold.discovery_website import _company_tokens

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
_WIKI_UA = "opencold/0.1 (company discovery channel)"

# Section headings whose entries are not active target companies.
_WIKI_SKIP_SECTIONS = (
    "defunct",
    "former",
    "closed",
    "merged",
    "dissolved",
    "renamed",
    "regulator",
    "regulators",
    "association",
    "associations",
    "see also",
    "references",
    "external links",
    "further reading",
    "notes",
    "bibliography",
)

# Names that are clearly not operating companies (regulators/indexes/meta).
_WIKI_NAME_BLOCKLIST_RE = re.compile(
    r"\b(authority|regulator|ministry|commission|federation|institute|academy|"
    r"index|list of|category|wikipedia|template|portal|see also)\b",
    re.IGNORECASE,
)


def _wiki_api_get(params: dict) -> dict:
    """GET the MediaWiki API as JSON. Returns {} on failure (best-effort).

    Retries once: Wikipedia occasionally times out / rate-limits, and a silent
    empty would drop the whole channel for the request (search harvest still
    covers it, but a cheap retry recovers most transient misses)."""
    url = WIKIPEDIA_API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": _WIKI_UA})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT + 5) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            if attempt == 0:
                time.sleep(0.5)
    return {}


def _clean_wiki_name(raw: str) -> str:
    """Reduce a wikitext fragment to a bare company name.

    Resolves [[target|text]] to text, strips refs/comments/templates/HTML and
    bold/italic markup, then cuts at a description separator (spaced dash or an
    opening paren) so 'Acme Ltd – the best (est. 1990)' -> 'Acme Ltd'. Keeps
    intra-name hyphens like 'Bradley-Hole' (only spaced dashes split)."""
    s = raw or ""
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]|]+)\]\]", r"\1", s)  # [[a|b]] -> b
    s = re.sub(r"<ref[^>]*?/>", "", s)
    s = re.sub(r"<ref.*?</ref>", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.DOTALL)
    s = re.sub(r"\{\{.*?\}\}", "", s, flags=re.DOTALL)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("'''", "").replace("''", "")
    s = re.split(r"\s+[-–—]\s+|\s*\(", s, maxsplit=1)[0]  # cut description
    s = re.sub(r"[\[\]{}|*#]", "", s)
    return _clean_text(s).strip(" .,-–—\t")


def _wikitable_first_cells(block: str) -> list[str]:
    """First data cell of each row in a {| ... |} wikitable block."""
    cells: list[str] = []
    for row in re.split(r"\n\s*\|-+", block):
        for line in row.splitlines():
            s = line.strip()
            if not s or s.startswith(("{|", "|}", "|+")):
                continue
            if s.startswith("!"):  # header row — no data cell
                break
            if s.startswith("|"):
                cell = s[1:]
                if "||" in cell:  # inline row: keep the first cell
                    cell = cell.split("||", 1)[0]
                if "|" in cell:  # strip a "style=...|" cell attribute
                    left, right = cell.split("|", 1)
                    if "=" in left and len(left) < 60:
                        cell = right
                cells.append(cell)
                break
    return cells


def _parse_wikitext_names(wikitext: str, max_names: int = 80) -> list[str]:
    """Candidate company names from a 'List of ...' page's wikitext.

    Handles the layouts these pages actually use: [[wikilinks]], bullet lists
    (incl. {{columns-list}}/{{div col}}), and the first column of {| wikitables.
    Section-aware: entries under Defunct/Regulators/See also/References/etc. are
    skipped. Heuristic by design — downstream ICP+region verification drops junk."""
    if not wikitext:
        return []
    names: list[str] = []
    seen: set[str] = set()

    def _emit(raw: str) -> None:
        name = _clean_wiki_name(raw)
        if not (2 <= len(name) <= 80) or _WIKI_NAME_BLOCKLIST_RE.search(name):
            return
        if not _company_tokens(name):
            return
        key = name.lower()
        if key not in seen:
            seen.add(key)
            names.append(name)

    skip = False
    in_table = False
    table_lines: list[str] = []
    for line in wikitext.splitlines():
        s = line.strip()
        heading = re.match(r"^=+\s*(.+?)\s*=+\s*$", s)
        if heading:
            skip = any(sec in heading.group(1).lower() for sec in _WIKI_SKIP_SECTIONS)
            continue
        if skip:
            continue
        if s.startswith("{|"):
            in_table, table_lines = True, [line]
            continue
        if in_table:
            table_lines.append(line)
            if s.startswith("|}"):
                for cell in _wikitable_first_cells("\n".join(table_lines)):
                    _emit(cell)
                in_table, table_lines = False, []
            continue
        bullet = re.match(r"^\*+\s*(.+)$", s)
        if bullet:
            _emit(bullet.group(1))
        elif s.startswith("[[") and "]]" in s:
            _emit(s)
        if len(names) >= max_names:
            break
    return names[:max_names]
