"""Optional embedding retrieval over the ONS SIC index (model2vec), fused with BM25.

Opt-in: set OPENCOLD_SIC_MATCHING=hybrid and install the extra
(`pip install 'opencold[semantic]'`). If the extra is missing or the model can't
load, matching silently stays lexical (BM25 only) -- never an error.

Index-row embeddings are computed on first use and cached at
~/.opencold/cache/sic_index_<model>_<index-hash>.npy; editing the index changes the
hash, so the cache rebuilds itself.
"""

from __future__ import annotations

import hashlib
import os
import re
from importlib import resources

# Multilingual so the same model can later serve cross-lingual ICP matching in discover.
MODEL = "minishlab/potion-multilingual-128M"
MATCHING_ENV = "OPENCOLD_SIC_MATCHING"  # "hybrid" | "lexical" (default)
RRF_K = 60  # standard Reciprocal Rank Fusion constant (Cormack et al. 2009); not tuned

_STATE: dict = {}  # model name -> (embed fn, index matrix, row codes) or None


def requested() -> bool:
    return os.environ.get(MATCHING_ENV, "").strip().lower() == "hybrid"


def _index_bytes() -> bytes:
    return resources.files("opencold").joinpath("sic_index_data.csv").read_bytes()


def cache_path(model: str, index_bytes: bytes):
    from opencold import config

    slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
    digest = hashlib.sha256(index_bytes).hexdigest()[:12]
    return config.CONFIG_DIR / "cache" / f"sic_index_{slug}_{digest}.npy"


def _load_model(model: str):
    """embed(texts) -> L2-normalised 2-D array, or None if model2vec/model is unavailable."""
    try:
        import numpy as np
        from model2vec import StaticModel

        m = StaticModel.from_pretrained(model)
    except Exception:
        return None

    def embed(texts):
        v = np.asarray(m.encode(list(texts)), dtype=np.float32)
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)

    return embed


def load(model: str | None = None, embedder=None):
    """(embed, matrix, codes) for `model`, memoised per process; None on any failure.
    `embedder` injects a fake for tests (no download)."""
    model = model or MODEL
    if model in _STATE and embedder is None:
        return _STATE[model]
    state = None
    try:
        import csv
        import io

        import numpy as np

        embed = embedder or _load_model(model)
        if embed is not None:
            raw = _index_bytes()
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
            path = cache_path(model, raw)
            try:
                matrix = np.load(path)
            except Exception:
                matrix = embed([r["activity"] for r in rows])
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    np.save(path, matrix)
                except Exception:
                    pass  # cache is best-effort
            state = (embed, matrix, [r["sic"] for r in rows])
    except Exception:
        state = None
    if embedder is None:
        _STATE[model] = state
    return state


def code_similarity(icp: str, state) -> dict[str, float]:
    """SIC code -> best cosine similarity between the ICP and any of its index rows."""
    embed, matrix, codes = state
    sims = matrix @ embed([icp])[0]
    best: dict[str, float] = {}
    for code, s in zip(codes, sims.tolist(), strict=True):
        if s > best.get(code, -2.0):
            best[code] = s
    return best


def rrf(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal Rank Fusion, normalised to 0..1 by its maximum (rank 1 in every
    ranking): a code first in both lists scores 1.0, first in only one scores ~0.5."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, code in enumerate(ranking, 1):
            fused[code] = fused.get(code, 0.0) + 1.0 / (k + rank)
    top = len(rankings) / (k + 1)
    return {c: s / top for c, s in fused.items()} if rankings else {}


def fuse(bm25: dict[str, float], sims: dict[str, float]) -> dict[str, float]:
    """RRF of the BM25 ranking (codes with any lexical hit) and the embedding ranking."""
    by_bm25 = sorted((c for c, s in bm25.items() if s > 0), key=lambda c: (-bm25[c], c))
    by_sim = sorted(sims, key=lambda c: (-sims[c], c))
    return rrf([by_bm25, by_sim])
