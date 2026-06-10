"""Tests for semantic ICP expansion (lexicon + Datamuse + optional LLM tiers).

All network/LLM is mocked, so the suite runs offline and fast. An autouse fixture
isolates the on-disk expansion cache (and any user-override lexicon) to a tmp dir.
"""

import json
from unittest.mock import patch

import pytest

from opencold import icp_expansion, config, discovery
from opencold.discovery import CandidateCompany


def patch_urlopen(resp):
    return patch("urllib.request.urlopen", return_value=resp)


def patch_urlopen_raises(exc):
    return patch("urllib.request.urlopen", side_effect=exc)


def patch_complete(text):
    return patch("opencold.generator.complete", return_value=text)


def patch_complete_raises(exc):
    return patch("opencold.generator.complete", side_effect=exc)


def _fetch_for(host_html: dict):
    def _fake(url, timeout=None):
        return host_html.get(discovery.normalize_domain(url))
    return _fake


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(icp_expansion, "_DISK_CACHE", None)
    yield


class _FakeResp:
    """Minimal urlopen() context-manager stand-in returning a fixed JSON body."""
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self._body


class TestLexicon:
    def test_lookup_exact(self):
        terms = icp_expansion._lexicon_terms("timber")
        assert {"wood", "lumber", "sawmill", "plywood"} <= terms

    def test_lookup_morphology(self):
        assert "sawmill" in icp_expansion._lexicon_terms("Timber Merchants")
        assert "sawmill" in icp_expansion._lexicon_terms("timber companies")

    def test_unknown_industry_empty(self):
        assert icp_expansion._lexicon_terms("quux widgetry") == set()

    def test_user_override_merges(self, tmp_path):
        (tmp_path / "icp_synonyms.json").write_text('{"timber": ["bespoke-thing"]}', encoding="utf-8")
        terms = icp_expansion._lexicon_terms("timber")
        assert "bespoke-thing" in terms      # user term added
        assert "sawmill" in terms            # built-ins still present

    def test_bad_override_ignored(self, tmp_path):
        (tmp_path / "icp_synonyms.json").write_text("{ not json", encoding="utf-8")
        assert "sawmill" in icp_expansion._lexicon_terms("timber")

    def test_symmetric_lookup(self):
        # The lexicon is symmetric: any cluster member expands to the rest (A<->B<->C),
        # not only the canonical key. "wood"/"sawmill" reach "timber" and each other.
        assert {"timber", "lumber", "sawmill"} <= icp_expansion._lexicon_terms("wood")
        assert {"timber", "wood", "plywood"} <= icp_expansion._lexicon_terms("sawmill")
        assert "timber" in icp_expansion._lexicon_terms("plywood")

    def test_user_override_is_symmetric(self, tmp_path):
        (tmp_path / "icp_synonyms.json").write_text('{"timber": ["xylophonics"]}', encoding="utf-8")
        # override link works in reverse too (xylophonics -> timber cluster)
        assert "timber" in icp_expansion._lexicon_terms("xylophonics")

    def test_short_key_not_substring_matched(self):
        # Short symmetric keys (ev, tax, hr) must NOT hit inside unrelated words.
        assert icp_expansion._lexicon_terms("developer") == set()   # 'ev' inside developer
        assert icp_expansion._lexicon_terms("taxi") == set()        # 'tax' inside taxi
        assert icp_expansion._lexicon_terms("threads") == set()     # 'hr' inside threads

    def test_polysemous_terms_excluded_as_keys(self):
        # Cross-industry-polysemous values are kept out of clusters, so they don't
        # become misleading reverse keys.
        for t in ("policy", "claims", "api", "platform", "agency", "developer"):
            assert icp_expansion._lexicon_terms(t) == set(), t

    def test_hub_spoke_not_overlinked(self):
        # A courier is logistics-adjacent but not a warehouse; the tight cluster keeps
        # them apart even though both are "logistics".
        assert "warehousing" not in icp_expansion._lexicon_terms("courier")
        assert "courier" not in icp_expansion._lexicon_terms("warehousing")

    def test_experiment_gap_clusters_covered(self):
        # These ICPs returned ZERO lexicon terms in the Datamuse help-vs-harm
        # experiment; coverage now comes from curated clusters, offline.
        assert {"pulp mill", "papermaking"} <= icp_expansion._lexicon_terms("Paper Mill")
        assert "additive manufacturing" in icp_expansion._lexicon_terms("3D printing services")
        assert {"vineyard", "vintner"} <= icp_expansion._lexicon_terms("Wine producers")
        assert {"arabica", "robusta"} <= icp_expansion._lexicon_terms("Coffee exporter")
        assert "skincare" in icp_expansion._lexicon_terms("Organic cosmetics brands")
        # "paper" alone stays out (polysemous: newspaper, research paper).
        assert icp_expansion._lexicon_terms("paper") == set()

    def test_cluster_hygiene(self):
        # Mechanical guard for the failure classes this lexicon has already paid
        # for: members double as matcher evidence and reverse keys, so no member
        # may be a generic ICP word, an expansion stopword, a documented
        # cross-industry polyseme, an everyday word measured to leak ("health"),
        # or geography (country/city/demonym — region fit has its own layer).
        from opencold import icp_phrases, icp_synonyms
        banned = (
            icp_phrases.GENERIC_ICP_TERMS
            | icp_expansion._EXTRA_STOPWORDS
            | {"policy", "claims", "api", "developer", "agency", "platform",
               "media", "power", "infrastructure", "health", "casting", "studio"}
        )
        geo = icp_expansion._geo_terms()
        for cluster in icp_synonyms.CLUSTERS:
            for member in cluster:
                m = member.strip().lower()
                assert m == member and len(m) >= 2, f"unnormalised member: {member!r}"
                assert m not in banned, f"banned member: {member!r}"
                assert m not in geo, f"geographic member: {member!r}"

    def test_new_vertical_coverage(self):
        # Spot checks across the deepened verticals (single-word stem keys and
        # multi-word substring keys both fire).
        assert "metal fabrication" in icp_expansion._lexicon_terms("Welding services")
        assert "venture capital" in icp_expansion._lexicon_terms("Private Equity firms")
        assert "barbershop" in icp_expansion._lexicon_terms("hairdressers")
        assert "wind turbines" in icp_expansion._lexicon_terms("wind farm developers")
        assert "abattoir" in icp_expansion._lexicon_terms("Meat exporters")
        assert "luminaires" in icp_expansion._lexicon_terms("LED lighting manufacturers")
        assert "fuel cell" in icp_expansion._lexicon_terms("green hydrogen")
        assert "veterinarian" in icp_expansion._lexicon_terms("Veterinary clinics")

    def test_deliberate_separation_kept(self):
        # Adjacent industries stay un-bridged: physical security is not cyber,
        # cold chain is not general warehousing, banking never keys from "bank"
        # (bare "banking"/"bank" stem-match "bank transfer" on any contact page).
        assert "cctv" not in icp_expansion._lexicon_terms("cybersecurity")
        assert "warehousing" not in icp_expansion._lexicon_terms("cold chain")
        assert icp_expansion._lexicon_terms("bank") == set()


class TestDatamuse:
    def test_parsed_and_filtered(self):
        payload = [{"word": "lumber"}, {"word": "sawmill"}, {"word": "the"},
                   {"word": "services"}, {"word": "123"}, {"word": "wood products"}]
        with patch_urlopen(_FakeResp(payload)):
            out = icp_expansion._datamuse("timber")
        assert "lumber" in out and "sawmill" in out and "wood products" in out
        for junk in ("the", "services", "123"):
            assert junk not in out

    def test_everyday_english_filtered_by_frequency(self):
        # Measured harm: ml("plumbing") returns water(278/M)/line(187)/health(161) —
        # enough for an insurance page to pass the weak-evidence gate. Specific
        # industry terms sit far below the ceiling; untagged results are kept.
        payload = [{"word": "water", "tags": ["f:278.40"]},
                   {"word": "health", "tags": ["f:161.05"]},
                   {"word": "sewerage", "tags": ["f:0.52"]},
                   {"word": "pipework", "tags": ["f:bogus"]},
                   {"word": "drainlayer"}]
        with patch_urlopen(_FakeResp(payload)):
            out = icp_expansion._datamuse("plumbing")
        assert out == ["sewerage", "pipework", "drainlayer"]

    def test_returns_ordered_list(self):
        payload = [{"word": "lumber"}, {"word": "sawmill"}]
        with patch_urlopen(_FakeResp(payload)):
            out = icp_expansion._datamuse("timber")
        assert isinstance(out, list)
        assert out[:2] == ["lumber", "sawmill"]  # relevance order preserved, deduped

    def test_failsilent(self):
        with patch_urlopen_raises(OSError("no network")):
            assert icp_expansion._datamuse("timber") == []


class TestLlm:
    def test_parsed_and_filtered(self):
        with patch_complete('{"terms": ["sawmill", "plywood", "services"]}'):
            out = icp_expansion._llm_terms("timber", {"type": "anthropic", "api_key": "x"})
        assert {"sawmill", "plywood"} <= out
        assert "services" not in out

    def test_failsilent(self):
        with patch_complete_raises(RuntimeError("boom")):
            assert icp_expansion._llm_terms("timber", {"type": "x"}) == set()


class TestExpandIcp:
    def test_offline_lexicon_only(self):
        out = icp_expansion.expand_icp("timber", use_llm=False, use_datamuse=False)
        assert {"wood", "lumber", "sawmill"} <= out
        assert "timber" not in out  # original ICP token is dropped (it already matches)

    def test_no_provider_skips_llm(self):
        with patch_complete('{"terms": ["x"]}') as comp:
            out = icp_expansion.expand_icp("timber", use_llm=True, provider=None, use_datamuse=False)
        comp.assert_not_called()
        assert "sawmill" in out

    def test_cap_enforced(self, monkeypatch):
        monkeypatch.setattr(icp_expansion, "_lexicon_terms",
                            lambda icp: {f"term{i}" for i in range(60)})
        out = icp_expansion.expand_icp("timber", use_llm=False, use_datamuse=False)
        assert len(out) <= icp_expansion.MAX_EXPANSION_TERMS

    def test_lexicon_prioritized_over_datamuse(self, monkeypatch):
        # Lexicon terms fill the cap before noisier Datamuse terms.
        monkeypatch.setattr(icp_expansion, "_datamuse",
                            lambda tok, rels=("ml", "rel_trg"): ["geyser", "blacksmith"])
        out = icp_expansion.expand_icp("timber", use_llm=False, use_datamuse=True)
        assert "sawmill" in out  # curated kept


class TestGroupedExpansion:
    def test_lexicon_attribution_per_token(self):
        flat, by_token = icp_expansion._lexicon_terms_grouped("Sustainability Consultancy for SMEs")
        assert "esg" in by_token["sustainability"]
        assert "advisory" in by_token["consultancy"]
        # Same-meaning cluster members never cross tokens.
        assert "advisory" not in by_token["sustainability"]
        assert "esg" not in by_token["consultancy"]
        assert flat == set().union(*by_token.values())

    def test_multiword_key_attributes_to_contained_tokens(self):
        # "waste management" is a lexicon key: its cluster vouches for BOTH tokens
        # (trusted phrase-level equivalence).
        _, by_token = icp_expansion._lexicon_terms_grouped("Waste Management")
        assert "recycling" in by_token["waste"]
        assert "recycling" in by_token["management"]

    def test_datamuse_attribution_by_relation_quality(self):
        # Per-token means-like results attribute; phrase-level results and loose
        # per-token associations (coffee -> urn) stay flat-only.
        def fake_dm(term, rels=("ml", "rel_trg")):
            if term == "paper mill":
                return ["paperworks"]                      # phrase-level: flat only
            if rels == ("ml",):
                return {"paper": ["pulp"], "mill": ["milling"]}.get(term, [])
            if rels == ("rel_trg",):
                return {"paper": ["stationery"], "mill": ["grindstone"]}.get(term, [])
            return []

        with patch.object(icp_expansion, "_datamuse", side_effect=fake_dm):
            result = icp_expansion.expand_icp_grouped("Paper Mill", use_llm=False)
        assert {"paperworks", "pulp", "milling", "stationery", "grindstone"} <= result.flat
        assert "pulp" in result.by_token["paper"]
        assert "milling" in result.by_token["mill"]
        attributed = set().union(*result.by_token.values())
        assert "paperworks" not in attributed      # phrase-level never attributes
        assert "stationery" not in attributed      # associations never attribute
        assert "grindstone" not in attributed
        # ...while lexicon phrase-key members ARE attributed, to both tokens.
        assert "pulp mill" in result.by_token["paper"]
        assert "pulp mill" in result.by_token["mill"]

    def test_attributed_terms_survive_phrase_flood(self):
        # Regression (coffee exporter): phrase-level results used to fill the cap
        # first, starving the attributable per-token terms out of `flat`.
        def fake_dm(term, rels=("ml", "rel_trg")):
            if term == "paper mill":
                return [f"noise{i}" for i in range(40)]
            if rels == ("ml",):
                return {"paper": ["pulp"], "mill": ["milling"]}.get(term, [])
            return []

        with patch.object(icp_expansion, "_datamuse", side_effect=fake_dm):
            result = icp_expansion.expand_icp_grouped("Paper Mill", use_llm=False)
        assert "pulp" in result.by_token["paper"]
        assert "milling" in result.by_token["mill"]

    def test_geo_terms_never_expansion_candidates(self):
        # Datamuse associates "coffee exporter" with producer countries; a region
        # word as a matcher term makes every local site "match" the ICP.
        for geo in ("uganda", "ugandan", "kampala", "ethiopia", "brazil"):
            assert not icp_expansion._good_candidate(geo), geo
        assert icp_expansion._good_candidate("arabica")

    def test_views_never_disagree(self):
        with patch.object(icp_expansion, "_datamuse", return_value=[]):
            result = icp_expansion.expand_icp_grouped("timber", use_llm=False)
        for terms in result.by_token.values():
            assert terms <= result.flat

    def test_grouped_cache_round_trip(self):
        with patch.object(icp_expansion, "_datamuse", return_value=["lumberjack"]) as dm:
            a = icp_expansion.expand_icp_grouped("timber", use_llm=False)
            first_calls = dm.call_count
            b = icp_expansion.expand_icp_grouped("timber", use_llm=False)
        assert dm.call_count == first_calls       # second call served from cache
        assert a.flat == b.flat and a.by_token == b.by_token

    def test_flat_view_delegates(self):
        with patch.object(icp_expansion, "_datamuse", return_value=[]):
            assert icp_expansion.expand_icp("timber", use_llm=False) == \
                icp_expansion.expand_icp_grouped("timber", use_llm=False).flat

    def test_cache_key_preserves_core_order(self):
        assert icp_expansion._norm_v2("Sustainability Consultancy") != \
            icp_expansion._norm_v2("Consultancy for Sustainability")


class TestCache:
    def test_round_trip_no_second_network(self, monkeypatch):
        calls = {"n": 0}

        def fake_dm(tok, rels=("ml", "rel_trg")):
            calls["n"] += 1
            return ["lumber"]

        monkeypatch.setattr(icp_expansion, "_datamuse", fake_dm)
        a = icp_expansion.expand_icp("timber", use_llm=False, use_datamuse=True)
        after_first = calls["n"]
        b = icp_expansion.expand_icp("timber", use_llm=False, use_datamuse=True)
        assert a == b
        assert calls["n"] == after_first  # second call served from cache
        assert (config.CONFIG_DIR / "icp_expansions.json").exists()

    def test_sig_separates_llm_on_off(self, monkeypatch):
        monkeypatch.setattr(icp_expansion, "_datamuse", lambda tok, rels=("ml", "rel_trg"): [])
        icp_expansion.expand_icp("timber", use_llm=False, use_datamuse=True)
        with patch_complete('{"terms": ["sawmill"]}'):
            icp_expansion.expand_icp("timber", use_llm=True, provider={"type": "x"}, use_datamuse=True)
        keys = list(icp_expansion._load_cache().keys())
        assert any(k.endswith("|v6l1d") for k in keys)
        assert any(k.endswith("|v6l1dm") for k in keys)


class TestExpansionQueries:
    def test_capped_and_sorted(self):
        q = icp_expansion.expansion_queries({"e", "d", "c", "b", "a"}, "UK", cap=3)
        assert q == ["a companies in UK", "b companies in UK", "c companies in UK"]

    def test_empty_region(self):
        assert icp_expansion.expansion_queries({"wood"}, "") == []


class TestIntegrationMatching:
    def _cand(self):
        return CandidateCompany("Acme", "https://acme.test", "src", "search", "search")

    def test_expansion_scores_and_appears_in_matched(self):
        enr = {"website_status": "ok",
               "company_summary": "local sawmill and plywood supplier",
               "personalization_facts": ""}
        score, matched = discovery.score_company(self._cand(), enr, "timber",
                                                 weak_terms={"sawmill", "plywood"})
        assert score > 35
        assert "sawmill" in matched and "plywood" in matched

    def test_expansion_widens_evidence_gate(self):
        enr = {"company_summary": "hardwood joinery workshop", "personalization_facts": ""}
        assert discovery._icp_evidence("timber", enr, {"hardwood", "joinery"}) is True
        assert discovery._icp_evidence("timber", enr, set()) is False

    def test_core_term_outscores_expansion_only(self):
        cand = self._cand()
        core = {"website_status": "ok", "company_summary": "timber yard", "personalization_facts": ""}
        weak = {"website_status": "ok", "company_summary": "sawmill yard", "personalization_facts": ""}
        core_score, _ = discovery.score_company(cand, core, "timber", weak_terms={"sawmill"})
        weak_score, _ = discovery.score_company(cand, weak, "timber", weak_terms={"sawmill"})
        assert core_score > weak_score


class TestExpansionEndToEnd:
    def test_expansion_flows_into_company_row(self):
        candidates = [CandidateCompany("Yildiz Wood", "https://yildiz.test", "src", "search", "search")]
        html = {"yildiz.test": "<html><body><h1>Yildiz Wood</h1>"
                               "<p>We run a modern sawmill and plywood plant.</p></body></html>"}
        with patch("opencold.discovery.discover_company_candidates", return_value=candidates), \
             patch("opencold.discovery.web_search", return_value=[]), \
             patch("opencold.enricher._fetch_html", _fetch_for(html)), \
             patch("opencold.icp_expansion.expand_icp_grouped",
                   return_value=icp_expansion.ExpansionResult(
                       flat={"sawmill", "plywood"},
                       by_token={"timber": {"sawmill", "plywood"}})):
            rows = discovery.discover_company_rows("timber", "United States", limit=5, use_llm=False)
        row = next(r for r in rows if "Yildiz" in (r.get("company") or ""))
        assert "sawmill" in row["matched_terms"] or "plywood" in row["matched_terms"]
