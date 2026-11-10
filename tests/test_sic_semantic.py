"""Hybrid SIC retrieval with a fake, deterministic embedder (never the real model)."""

import hashlib

import numpy as np
import pytest

from opencold import sic_match, sic_semantic

DIM = 64


def fake_embedder(calls=None):
    """Hashed bag-of-words vectors: texts sharing words are similar. Deterministic."""

    def embed(texts):
        if calls is not None:
            calls.append(len(texts))
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in t.lower().split():
                out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-12)

    return embed


def test_rrf_scores_and_normalisation():
    fused = sic_semantic.rrf([["a", "b"], ["b", "c"]], k=60)
    assert fused["b"] == pytest.approx((1 / 62 + 1 / 61) / (2 / 61))
    assert fused["a"] == pytest.approx((1 / 61) / (2 / 61))  # first in one list -> 0.5
    assert max(fused, key=fused.get) == "b"


def test_fuse_ignores_codes_without_a_lexical_hit_in_the_bm25_list():
    fused = sic_semantic.fuse({"x": 0.9, "y": 0.0}, {"y": 0.8, "x": 0.1})
    assert fused["x"] == pytest.approx(1.0 * 0.5 + (1 / 62) / (2 / 61))
    assert fused["y"] == pytest.approx((1 / 61) / (2 / 61))


def test_embeddings_cached_on_first_use(tmp_config):
    calls = []
    state = sic_semantic.load("fake/model", embedder=fake_embedder(calls))
    path = sic_semantic.cache_path("fake/model", sic_semantic._index_bytes())
    assert path.exists() and path.parent.name == "cache"
    assert np.load(path).shape == (len(state[2]), DIM)
    calls.clear()
    sic_semantic.load("fake/model", embedder=fake_embedder(calls))
    assert calls == []  # index read from cache; the embedder wasn't asked for rows


def test_cache_key_changes_with_the_index():
    a = sic_semantic.cache_path("m", b"sic,activity\n1,a\n")
    b = sic_semantic.cache_path("m", b"sic,activity\n1,b\n")
    assert a != b and a.name.startswith("sic_index_m_")


def test_hybrid_mode_with_fake_embedder(tmp_config, monkeypatch):
    state = sic_semantic.load("fake/model", embedder=fake_embedder())
    monkeypatch.setenv(sic_semantic.MATCHING_ENV, "hybrid")
    monkeypatch.setattr(sic_semantic, "load", lambda *a, **k: state)
    res = sic_match.match_icp_to_sics("dental clinics")
    again = sic_match.match_icp_to_sics("dental clinics")
    assert res.mode == "hybrid"
    assert [m.code for m in res.matches] == [m.code for m in again.matches]  # deterministic
    assert "86230" in [m.code for m in res.matches]


def test_falls_back_to_lexical_when_model_unavailable(monkeypatch):
    monkeypatch.setenv(sic_semantic.MATCHING_ENV, "hybrid")
    monkeypatch.setattr(sic_semantic, "_load_model", lambda model: None)
    monkeypatch.setattr(sic_semantic, "_STATE", {})
    res = sic_match.match_icp_to_sics("dental clinics")
    assert res.mode == "lexical"
    assert res.matches[0].code == "86230"


def test_lexical_by_default():
    assert sic_match.match_icp_to_sics("dental clinics").mode == "lexical"
