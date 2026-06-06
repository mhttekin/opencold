"""Keyless, best-effort text translation for multilingual discovery.

Rotates across public Lingva Translate instances (privacy-respecting proxies in
front of Google Translate), falling back to MyMemory, then to the original text.
This module never raises: a translation failure degrades discovery to its
previous English-only behaviour rather than breaking a run. No API keys, no
signup — suitable for a hosted, free-to-use front-end.

Volume is kept tiny by design (the callers translate the ICP keyword and each
company's already-distilled facts, never raw HTML), and every result is cached
for the process lifetime, so free public instances are not hammered.
"""

from __future__ import annotations

import json
import random
import urllib.parse
import urllib.request

# Public Lingva mirrors (https://github.com/thedaviddelta/lingva-translate).
# No single volunteer instance is reliable, so we rotate: a pool is the
# reliability mechanism, exactly like the ddgs -> Brave -> Serper search rotation.
_LINGVA_INSTANCES = (
    "https://lingva.ml",
    "https://translate.plausibility.cloud",
    "https://lingva.garudalinux.org",
    "https://translate.projectsegfau.lt",
    "https://lingva.lunar.icu",
    "https://translate.dr460nf1r3.org",
    "https://translate.igna.wtf",
    "https://translate.jae.fi",
)
_MYMEMORY = "https://api.mymemory.translated.net/get"
_UA = "opencold/0.1 (discovery translation)"
_TIMEOUT = 4.0

# Our inputs are short (keywords, ≤5 distilled facts); skip pathological blobs
# rather than risk a slow request or a provider rejection.
MAX_CHARS = 4500

# Process-lifetime cache keyed by (text, source, target). The ICP keyword and
# repeated facts recur across a run, collapsing most calls to a dict hit.
_CACHE: dict[tuple[str, str, str], str] = {}


def _get(url: str, timeout: float = _TIMEOUT) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(200_000).decode("utf-8", errors="replace")
    except Exception:
        return None


def _lingva(text: str, target: str, source: str) -> str | None:
    """Translate via a rotating pool of Lingva instances. First hit wins."""
    path = "/".join(("api", "v1", source, target, urllib.parse.quote(text, safe="")))
    start = random.randrange(len(_LINGVA_INSTANCES))
    for offset in range(len(_LINGVA_INSTANCES)):
        base = _LINGVA_INSTANCES[(start + offset) % len(_LINGVA_INSTANCES)]
        body = _get(f"{base}/{path}")
        if not body:
            continue
        try:
            translation = json.loads(body).get("translation")
        except (ValueError, AttributeError):
            continue
        if isinstance(translation, str) and translation.strip():
            return translation.strip()
    return None


def _mymemory(text: str, target: str, source: str) -> str | None:
    """Low-volume fallback. Needs an explicit source, so it can't serve the
    auto-detect (page-text) case — that degrades to untranslated text instead."""
    if source == "auto":
        return None
    query = urllib.parse.urlencode({"q": text, "langpair": f"{source}|{target}"})
    body = _get(f"{_MYMEMORY}?{query}")
    if not body:
        return None
    try:
        translation = json.loads(body).get("responseData", {}).get("translatedText")
    except (ValueError, AttributeError):
        return None
    if isinstance(translation, str) and translation.strip():
        return translation.strip()
    return None


def translate(text: str, target: str, source: str = "auto") -> str:
    """Best-effort translate `text` into `target` (ISO code). Returns the input
    unchanged on any failure — translation is never fatal to discovery."""
    if not target or not text or not text.strip():
        return text
    src = source or "auto"
    if target == src:
        return text
    if len(text) > MAX_CHARS:
        return text
    key = (text, src, target)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    result = _lingva(text, target, src) or _mymemory(text, target, src) or text
    _CACHE[key] = result
    return result


def translate_many(texts: list[str], target: str, source: str = "auto") -> list[str]:
    """Translate a list, preserving order. Identical strings collapse via the
    shared cache, so duplicates cost one network call at most."""
    return [translate(text, target, source) for text in texts]
