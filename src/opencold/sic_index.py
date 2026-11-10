"""BM25 over the ONS UK SIC 2007 alphabetical index (offline, deterministic).

~16k ONS activity phrases ("Pallets made of plastic (manufacture)" -> 22290) are
far more specific than the ~730 SIC titles, so they generate candidates the title
matcher misses. Terms are folded words passed through the same light inflectional
stemmer as the title matcher (pallets -> pallet); there is NO fuzzy or edit-distance
matching, so "pallet" and "pellet" stay different words.

Data: sic_index_data.csv, built by scripts/build_sic_index.py (see that script and
docs/architecture.md for source and Open Government Licence attribution).
"""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from functools import lru_cache
from importlib import resources

from opencold.icp_phrases import stem, text_words

K1, B = 1.2, 0.75  # standard BM25 parameters


def _terms(text: str, drop: frozenset[str]) -> list[str]:
    return [stem(w) for w in text_words(text) if len(w) > 2 and not w.isdigit() and w not in drop]


@lru_cache(maxsize=4)
def _index(drop: frozenset[str]):
    """(postings term -> [(doc, tf)], doc lengths, doc codes, N, avgdl)."""
    with resources.files("opencold").joinpath("sic_index_data.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
    lengths, codes = [], []
    for i, row in enumerate(rows):
        terms = _terms(row["activity"], drop)
        lengths.append(len(terms))
        codes.append(row["sic"])
        for term, tf in Counter(terms).items():
            postings[term].append((i, tf))
    n = len(rows)
    return postings, lengths, codes, n, (sum(lengths) / n if n else 0.0)


def _idf(df: int, n: int) -> float:
    return math.log(1 + (n - df + 0.5) / (df + 0.5))


def code_scores(query_words: list[str], drop: frozenset[str]) -> dict[str, float]:
    """SIC code -> 0..1 for the query: the code's best index row's BM25, divided by
    the query's total idf (unknown query words count at full idf, so an ICP word
    the index never uses lowers every score). Roughly: the idf-weighted share of
    the ICP that the best matching activity phrase covers."""
    postings, lengths, codes, n, avgdl = _index(drop)
    query = sorted({t for w in query_words for t in _terms(w, drop)})
    if not query or not n:
        return {}
    idf = {t: _idf(len(postings.get(t, ())), n) for t in query}
    doc_scores: dict[int, float] = defaultdict(float)
    for t in query:
        for doc, tf in postings.get(t, ()):
            norm = 1 - B + B * lengths[doc] / avgdl
            doc_scores[doc] += idf[t] * tf * (K1 + 1) / (tf + K1 * norm)
    total = sum(idf.values())
    best: dict[str, float] = {}
    for doc, s in doc_scores.items():
        code = codes[doc]
        best[code] = max(best.get(code, 0.0), min(s / total, 1.0))
    return best
