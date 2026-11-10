"""Tests for the smearch feature: ICP->SIC matching, the Companies House client,
SME scoring, CSV output, and the full pipeline.

All network is mocked (urllib.request.urlopen), so the suite runs offline. An
autouse fixture isolates config, neutralises the cwd .env auto-load, clears the
CH env vars, and resets the cleaned-SIC cache between tests.
"""

import base64
import csv
import json
import urllib.error
from unittest.mock import patch

import pytest

from opencold import companies_house as ch
from opencold import config, google_places, sic_categories, sic_match, sic_rank
from opencold import smearch as sm
from opencold import smearch_db as sdb
from opencold import smearch_enrich as se


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(config, "_DOTENV_LOADED", True)  # skip cwd .env auto-scan
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    monkeypatch.delenv("COMPANIES_HOUSE_BASE_URL", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    sic_match.reset_cache()
    yield
    sic_match.reset_cache()


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


_FIXTURE_SICS = [
    ("16100", "Sawmilling and planing of wood"),
    ("16290", "Manufacture of other products of wood, cork, straw and plaiting materials"),
    ("62012", "Business and domestic software development"),
    ("70229", "Management consultancy activities other than financial management"),
    ("47210", "Retail sale of fruit and vegetables in specialised stores"),
    ("01110", "Growing of cereals (except rice), leguminous crops and oil seeds"),
]


@pytest.fixture
def fixture_sics(monkeypatch):
    monkeypatch.setattr(sic_match, "load_sic_codes", lambda: _FIXTURE_SICS)
    # Title-matcher unit tests: the real ONS index would disagree with a fake SIC list,
    # and the low-confidence gate is tested on real data in tests/test_sic_index.py.
    monkeypatch.setattr(sic_match, "code_scores", lambda *a, **k: {})
    monkeypatch.setattr(sic_rank, "SIC_CONFIDENCE_MIN", 0.0)
    sic_match.reset_cache()
    yield


# Same subject ("food"), one SIC per role -- for role filter/ranking tests.
_ROLE_SICS = [
    ("10890", "Manufacture of other food products n.e.c."),
    ("46390", "Non-specialised wholesale of food, beverages and tobacco"),
    ("47290", "Other retail sale of food in specialised stores"),
]


@pytest.fixture
def role_sics(monkeypatch):
    monkeypatch.setattr(sic_match, "load_sic_codes", lambda: _ROLE_SICS)
    sic_match.reset_cache()
    yield


class TestCleanSicDescription:
    def test_strips_filler_keeps_signal(self):
        stems = sic_match.clean_sic_description("Sawmilling and planing of wood")
        assert "sawmill" in stems
        assert "wood" in stems
        assert "and" not in stems and "of" not in stems

    def test_drops_manufacture_and_other(self):
        stems = sic_match.clean_sic_description(
            "Manufacture of other products of wood, cork, straw and plaiting materials"
        )
        assert "wood" in stems and "cork" in stems
        assert "manufactur" not in stems and "manufacture" not in stems
        assert "other" not in stems and "products" not in stems

    def test_drops_except_clause_term(self):
        stems = sic_match.clean_sic_description(
            "Growing of cereals (except rice), leguminous crops and oil seeds"
        )
        assert "rice" not in stems  # the excluded term is dropped
        assert "cereal" in stems  # but the rest survives
        assert "oil" in stems and "seed" in stems

    def test_drops_short_and_digit_tokens(self):
        stems = sic_match.clean_sic_description(
            "Retail sale of fruit and vegetables in specialised stores"
        )
        assert "fruit" in stems and "vegetabl" in stems
        for filler in ("retail", "sale", "of", "in", "specialised", "stores"):
            assert filler not in stems


class TestMatchIcpToSics:
    def test_core_token_match(self, fixture_sics):
        res = sic_match.match_icp_to_sics("software development", set())
        assert res.status == "ok"
        assert res.matches[0].code == "62012"

    def test_expansion_synonym_half_weight(self, fixture_sics):
        res = sic_match.match_icp_to_sics("timber", {"sawmill", "wood"})
        codes = [m.code for m in res.matches]
        assert "16100" in codes
        hit = next(m for m in res.matches if m.code == "16100")
        assert {"sawmill", "wood"} <= set(hit.matched_terms)

    def test_min_score_relaxes(self, fixture_sics):
        res = sic_match.match_icp_to_sics("software development", set(), min_score=2.0)
        assert res.status == "relaxed"
        assert any(m.code == "62012" for m in res.matches)

    def test_max_sics_caps(self, fixture_sics):
        res = sic_match.match_icp_to_sics("consultancy", set(), max_sics=1)
        assert len(res.matches) == 1

    def test_generic_icp_flagged(self, fixture_sics):
        res = sic_match.match_icp_to_sics("manufacturing companies", set())
        assert res.status == "generic"
        assert res.signal_terms == []

    def test_no_match_is_empty(self, fixture_sics):
        res = sic_match.match_icp_to_sics("zzzqwerty gibberish", set())
        assert res.status == "empty"
        assert res.matches == []

    def test_matches_for_codes_override(self, fixture_sics):
        ms = sic_match.matches_for_codes(["16100", "62012"])
        assert [m.code for m in ms] == ["16100", "62012"]
        assert ms[0].description == "Sawmilling and planing of wood"


class TestRoleDimension:
    def test_detect_icp_roles(self):
        assert sic_match.detect_icp_roles("food manufacturing") == ["manufacture"]
        assert sic_match.detect_icp_roles("food") == []
        assert sic_match.detect_icp_roles("manufacturer and wholesaler of food") == [
            "manufacture",
            "wholesale",
        ]
        assert sic_match.detect_icp_roles("timber merchants") == ["wholesale"]
        assert sic_match.detect_icp_roles("a food shop") == ["retail"]

    def test_sic_role_from_title(self):
        assert sic_match.sic_role("Manufacture of other food products n.e.c.") == "manufacture"
        assert sic_match.sic_role("Processing and preserving of meat") == "manufacture"
        assert sic_match.sic_role("Non-specialised wholesale of food") == "wholesale"
        assert sic_match.sic_role("Agents involved in the sale of food") == "wholesale"
        assert sic_match.sic_role("Other retail sale of food in specialised stores") == "retail"
        assert sic_match.sic_role("Growing of rice") == "primary"
        assert sic_match.sic_role("Marine fishing") == "primary"
        assert sic_match.sic_role("Repair of computers and peripheral equipment") is None

    def test_role_words_not_treated_as_subject(self):
        stems = sic_match.clean_sic_description("Manufacture of bread")
        assert "bread" in stems
        assert "manufactur" not in stems and "manufacture" not in stems

    def test_no_role_ranks_mfg_then_wholesale_then_retail(self, role_sics):
        res = sic_match.match_icp_to_sics("food", set())
        assert [m.code for m in res.matches] == ["10890", "46390", "47290"]

    def test_role_filter_excludes_other_roles(self, role_sics):
        # The "food manufacturing -> only retail" bug: manufacture must drop retail/wholesale.
        res = sic_match.match_icp_to_sics("food", set(), roles=["manufacture"])
        assert [m.code for m in res.matches] == ["10890"]

    def test_multi_role_keeps_both(self, role_sics):
        res = sic_match.match_icp_to_sics("food", set(), roles=["manufacture", "wholesale"])
        assert {m.code for m in res.matches} == {"10890", "46390"}
        assert all(m.role != "retail" for m in res.matches)

    def test_primary_role_detection(self):
        assert sic_match.detect_icp_roles("dairy farming") == ["primary"]


class TestCategoryExpansion:
    def test_category_members(self):
        m = sic_categories.category_members("food")
        assert {"meat", "dairy", "fish", "bread"} <= m
        assert sic_categories.category_members("foods") == m  # plural via stem
        assert sic_categories.category_members("drinks") == sic_categories.category_members(
            "beverage"
        )  # alias
        assert sic_categories.category_members("widget") == set()  # not a category

    def test_food_reaches_meat_and_fish(self):
        # The reported gap: "food manufacturing" must reach meat/fish SICs, not
        # only those with the literal word "food". Uses the real vendored list.
        res = sic_match.match_icp_to_sics(
            "food manufacturing", set(), roles=["manufacture"], max_sics=30
        )
        codes = {m.code for m in res.matches}
        assert {"10110", "10120", "10130"} & codes  # meat processing/production
        assert "10200" in codes  # fish processing
        # manufacture or role-less only -- never wholesale/retail/primary.
        assert all(m.role in ("manufacture", None) for m in res.matches)

    def test_primary_sics_excluded_from_manufacture(self):
        res = sic_match.match_icp_to_sics(
            "food manufacturing", set(), roles=["manufacture"], max_sics=50
        )
        codes = {m.code for m in res.matches}
        assert "01470" not in codes  # Raising of poultry (farming)
        assert "03110" not in codes  # Marine fishing


class TestSearchCompanies:
    def test_auth_header_basic_empty_password(self):
        captured = {}

        def _fake(req, timeout=None):
            captured["auth"] = req.get_header("Authorization")
            return _FakeResp({"hits": 0, "items": []})

        with patch("urllib.request.urlopen", side_effect=_fake):
            ch.search_companies(["16100"], api_key="KEY", limit=5)
        assert captured["auth"] == "Basic " + base64.b64encode(b"KEY:").decode()

    def test_sic_and_type_joined(self):
        captured = {}

        def _fake(req, timeout=None):
            captured["url"] = req.full_url
            return _FakeResp({"hits": 0, "items": []})

        with patch("urllib.request.urlopen", side_effect=_fake):
            ch.search_companies(
                ["16100", "62012"], api_key="K", limit=5, company_types=("ltd", "llp")
            )
        assert "sic_codes=16100%2C62012" in captured["url"]
        assert "company_type=ltd%2Cllp" in captured["url"]
        assert "company_status=active" in captured["url"]

    def test_pagination_accumulates_and_advances(self):
        urls = []
        pages = [
            _FakeResp({"hits": 3, "items": [{"company_number": "1"}, {"company_number": "2"}]}),
            _FakeResp({"hits": 3, "items": [{"company_number": "3"}]}),
        ]

        def _fake(req, timeout=None):
            urls.append(req.full_url)
            return pages.pop(0)

        with patch("urllib.request.urlopen", side_effect=_fake):
            items = ch.search_companies(["16100"], api_key="K", limit=10)
        assert [i["company_number"] for i in items] == ["1", "2", "3"]
        assert "start_index=0" in urls[0] and "start_index=2" in urls[1]

    def test_respects_limit(self):
        page = _FakeResp({"hits": 50, "items": [{"company_number": "1"}, {"company_number": "2"}]})
        with patch("urllib.request.urlopen", return_value=page):
            items = ch.search_companies(["16100"], api_key="K", limit=1)
        assert len(items) == 1

    def test_start_index_offsets_first_fetch(self):
        # Pagination cursor: the first request starts at the given offset, then
        # advances by the page size as usual.
        urls = []
        pages = [
            _FakeResp({"hits": 200, "items": [{"company_number": "51"}]}),
            _FakeResp({"hits": 200, "items": [{"company_number": "52"}]}),
        ]

        def _fake(req, timeout=None):
            urls.append(req.full_url)
            return pages.pop(0)

        with patch("urllib.request.urlopen", side_effect=_fake):
            items = ch.search_companies(["16100"], api_key="K", limit=2, start_index=50)
        assert [i["company_number"] for i in items] == ["51", "52"]
        assert "start_index=50" in urls[0] and "start_index=51" in urls[1]

    def test_empty_items_stops(self):
        with patch("urllib.request.urlopen", return_value=_FakeResp({"hits": 0, "items": []})):
            assert ch.search_companies(["16100"], api_key="K", limit=10) == []

    def test_401_raises_auth_error(self):
        err = urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(ch.CompaniesHouseAuthError):
                ch.search_companies(["16100"], api_key="K", limit=5)

    def test_non_401_error_failsilent(self):
        err = urllib.error.HTTPError("http://x", 500, "err", {}, None)
        with patch("urllib.request.urlopen", side_effect=err):
            assert ch.search_companies(["16100"], api_key="K", limit=5) == []

    def test_400_raises_request_error(self):
        # A rejected filter value (e.g. a bad company_type) must surface, not
        # silently return "no companies".
        err = urllib.error.HTTPError("http://x", 400, "Bad Request", {}, None)
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(ch.CompaniesHouseRequestError):
                ch.search_companies(["16100"], api_key="K", limit=5)

    def test_enrichment_404_is_silent(self):
        # Non-strict enrichment: a 404 (no officers / missing profile) is empty,
        # not an error.
        err = urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)
        with patch("urllib.request.urlopen", side_effect=err):
            assert ch.get_company_officers("123", api_key="K") == {}
            assert ch.get_company_profile("123", api_key="K") == {}

    def test_no_codes_returns_empty(self):
        assert ch.search_companies([], api_key="K") == []


class TestDefaultSmeTypes:
    def test_excludes_api_rejected_types(self):
        # These were rejected by the live advanced-search company_type filter.
        assert "community-interest-company" not in ch.DEFAULT_SME_TYPES  # API 400
        assert "limited-partnership" not in ch.DEFAULT_SME_TYPES  # API 404
        assert "ltd" in ch.DEFAULT_SME_TYPES and "llp" in ch.DEFAULT_SME_TYPES


class TestBaseUrl:
    def test_default_is_live(self):
        assert ch.base_url() == ch.LIVE_BASE

    def test_use_sandbox_switches(self):
        ch.use_sandbox()
        assert ch.base_url() == ch.SANDBOX_BASE


class TestSmeScore:
    def test_fresh_micro_outranks_old_full(self):
        fresh = sm.sme_score("micro-entity", 2, 2024, 2026)
        old = sm.sme_score("full", 40, 2001, 2026)
        assert fresh > old
        assert fresh == pytest.approx(13.5)  # weighted max
        assert old == 0.0

    def test_unknown_is_neutral(self):
        assert sm.sme_score("", None, None, 2026) == pytest.approx(4.5)

    def test_recency_buckets(self):
        assert sm._recency_score(2026, 2026) == 3.0
        assert sm._recency_score(2022, 2026) == 2.0
        assert sm._recency_score(2018, 2026) == 1.0
        assert sm._recency_score(2000, 2026) == 0.0


class TestEnrichCompany:
    def test_enrich_pulls_signals(self):
        item = {"company_number": "123", "date_of_creation": "2024-01-01"}

        def _fake(req, timeout=None):
            url = req.full_url
            if "/officers" in url:
                return _FakeResp({"active_count": 2})
            return _FakeResp({"accounts": {"last_accounts": {"type": "micro-entity"}}})

        with patch("urllib.request.urlopen", side_effect=_fake):
            enr = sm.enrich_company(item, api_key="K", this_year=2026)
        assert enr.account_type == "micro-entity"
        assert enr.officer_count == 2
        assert enr.inc_year == 2024
        assert enr.sme == pytest.approx(13.5)


class TestCompanyToRowAndCsv:
    def test_defensive_flatten(self):
        enr = sm.EnrichedCompany(item={"company_number": "9"})
        row = sm.company_to_row(enr, [])
        assert set(row) == set(sm.CSV_FIELDS)
        assert row["company_url"].endswith("/company/9")
        assert row["locality"] == "" and row["account_type"] == ""

    def test_matched_sic_overlap(self):
        m = sic_match.SicMatch(
            "62012", "Business and domestic software development", 1.0, ["development"]
        )
        enr = sm.EnrichedCompany(item={"company_number": "1", "sic_codes": ["62012", "99999"]})
        row = sm.company_to_row(enr, [m])
        assert row["matched_sic_codes"] == "62012"
        assert "software development" in row["matched_sic_descriptions"]
        assert row["matched_icp_terms"] == "development"

    def test_csv_roundtrip(self, tmp_path):
        enr = sm.EnrichedCompany(item={"company_number": "1", "company_name": "Acme Ltd"}, sme=9.0)
        out = tmp_path / "out.csv"
        sm.write_smes_csv([sm.company_to_row(enr, [])], str(out))
        rows = list(csv.DictReader(out.open()))
        assert list(rows[0].keys()) == sm.CSV_FIELDS
        assert rows[0]["company_name"] == "Acme Ltd"

    def test_write_ignores_extra_keys(self, tmp_path):
        out = tmp_path / "out.csv"
        sm.write_smes_csv([{"company_name": "X", "surprise": "boom"}], str(out))
        assert "boom" not in out.read_text()


class TestGetKey:
    def test_env_var_used(self, monkeypatch):
        monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "envkey")
        assert ch.get_companies_house_key() == "envkey"

    def test_provider_config_fallback(self):
        config.add_provider("companies_house", "companies_house", "cfgkey")
        assert ch.get_companies_house_key() == "cfgkey"

    def test_missing_returns_none(self):
        assert ch.get_companies_house_key() is None


class TestLoadDotenv:
    def test_loads_without_override(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("COMPANIES_HOUSE_API_KEY=fromfile\n# comment\nFOO=bar\n")
        monkeypatch.setattr(config, "_DOTENV_LOADED", False)
        monkeypatch.delenv("FOO", raising=False)
        config.load_dotenv(str(env))
        import os

        assert os.environ["COMPANIES_HOUSE_API_KEY"] == "fromfile"
        assert os.environ["FOO"] == "bar"

    def test_does_not_override_existing(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("COMPANIES_HOUSE_API_KEY=fromfile\n")
        monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "preset")
        monkeypatch.setattr(config, "_DOTENV_LOADED", False)
        config.load_dotenv(str(env))
        import os

        assert os.environ["COMPANIES_HOUSE_API_KEY"] == "preset"


class TestPipeline:
    """End-to-end: --sic override -> search -> enrich -> score -> sorted CSV."""

    def test_run_smearch_ranks_and_writes(self, tmp_path):
        search_payload = {
            "hits": 2,
            "items": [
                {
                    "company_number": "OLD",
                    "company_name": "Old Oak Plc",
                    "company_status": "active",
                    "company_type": "ltd",
                    "date_of_creation": "2001-01-01",
                    "sic_codes": ["16100"],
                    "registered_office_address": {"locality": "Leeds", "postal_code": "LS1"},
                },
                {
                    "company_number": "NEW",
                    "company_name": "New Saw Ltd",
                    "company_status": "active",
                    "company_type": "ltd",
                    "date_of_creation": "2024-01-01",
                    "sic_codes": ["16100"],
                    "registered_office_address": {"locality": "Hull", "postal_code": "HU1"},
                },
            ],
        }
        profiles = {
            "OLD": {"accounts": {"last_accounts": {"type": "full"}}},
            "NEW": {"accounts": {"last_accounts": {"type": "micro-entity"}}},
        }
        officers = {"OLD": {"active_count": 25}, "NEW": {"active_count": 2}}

        def _fake(req, timeout=None):
            url = req.full_url
            if "/advanced-search/" in url:
                return _FakeResp(search_payload)
            num = url.split("/company/")[1].split("?")[0].split("/")[0]
            if "/officers" in url:
                return _FakeResp(officers.get(num, {}))
            return _FakeResp(profiles.get(num, {}))

        out = tmp_path / "smes.csv"
        with patch("urllib.request.urlopen", side_effect=_fake):
            result = sm.run_smearch(
                "",
                sic_codes=["16100"],
                api_key="K",
                output=str(out),
                limit=10,
                this_year=2026,
            )
        assert len(result.rows) == 2
        # Fresh micro-SME ranks above the old full-accounts company.
        assert result.rows[0]["company_name"] == "New Saw Ltd"
        assert float(result.rows[0]["sme_score"]) > float(result.rows[1]["sme_score"])
        # CSV written with the ranked order preserved.
        disk = list(csv.DictReader(out.open()))
        assert [r["company_number"] for r in disk] == ["NEW", "OLD"]
        assert disk[0]["account_type"] == "micro-entity"
        assert disk[0]["matched_sic_codes"] == "16100"

    def test_dry_run_skips_network(self, tmp_path):
        # No urlopen patch: if it tried to call the network the test would error.
        result = sm.run_smearch(
            "", sic_codes=["16100"], api_key="K", dry_run=True, output=str(tmp_path / "x.csv")
        )
        assert result.rows == []
        assert result.match.matches[0].code == "16100"


class TestPagination:
    """--page rides on a CH start_index cursor; page 1 starts at 0, each page
    advances by --limit. The page<->index map is the reusable primitive."""

    def test_page_to_start_index(self):
        assert sm.page_to_start_index(1, 50) == 0
        assert sm.page_to_start_index(2, 50) == 50
        assert sm.page_to_start_index(3, 20) == 40
        # Page <= 1 (and junk) clamps to the first page.
        assert sm.page_to_start_index(0, 50) == 0
        assert sm.page_to_start_index(-4, 50) == 0

    def test_run_smearch_forwards_start_index(self):
        # The cursor reaches the CH advanced-search query unchanged.
        urls = []

        def _fake(req, timeout=None):
            urls.append(req.full_url)
            return _FakeResp({"hits": 0, "items": []})

        with patch("urllib.request.urlopen", side_effect=_fake):
            sm.run_smearch(
                "",
                sic_codes=["16100"],
                api_key="K",
                output="",
                limit=10,
                start_index=20,
                this_year=2026,
            )
        assert urls and "start_index=20" in urls[0]


class TestSmearchDb:
    """The seen-companies store backing smearch's default 'always fresh' action."""

    def test_roundtrip_and_dedup(self, tmp_path):
        conn = sdb.connect(tmp_path / "seen.db")
        rows = [
            {"company_number": "A", "company_name": "Alpha", "sic_codes": "16100"},
            {"company_number": "B", "company_name": "Bravo", "sic_codes": "16100"},
            {"company_number": "", "company_name": "NoNumber"},
        ]  # no number -> skipped
        assert sdb.mark_enriched(conn, rows, icp="timber") == 2
        assert sdb.seen_numbers(conn, ["A", "B", "C"]) == {"A", "B"}

    def test_mark_is_idempotent(self, tmp_path):
        conn = sdb.connect(tmp_path / "seen.db")
        sdb.mark_enriched(conn, [{"company_number": "A"}])
        # Re-recording A is a no-op; only B is newly inserted.
        assert sdb.mark_enriched(conn, [{"company_number": "A"}, {"company_number": "B"}]) == 1
        assert sdb.seen_numbers(conn, ["A", "B"]) == {"A", "B"}

    def test_persists_across_connections(self, tmp_path):
        path = tmp_path / "seen.db"
        c1 = sdb.connect(path)
        sdb.mark_enriched(c1, [{"company_number": "A"}])
        c1.close()
        assert sdb.seen_numbers(sdb.connect(path), ["A"]) == {"A"}

    def test_default_path_honours_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCOLD_SMEARCH_DB", str(tmp_path / "custom.db"))
        assert sdb.default_db_path() == tmp_path / "custom.db"


class TestGatherFreshPages:
    """Page-walk that keeps surfacing unseen companies (smearch's default)."""

    @staticmethod
    def _rows(*nums):
        return [{"company_number": n} for n in nums]

    def test_no_dedup_is_single_page(self):
        calls = []

        def collect(pg):
            calls.append(pg)
            return self._rows("A", "B", "C")

        g = sm.gather_fresh_pages(collect, start_page=1, target=2, is_seen=None)
        assert [r["company_number"] for r in g.rows] == ["A", "B", "C"]
        assert calls == [1] and g.skipped_seen == 0  # is_seen=None -> exactly one page

    def test_whole_page_seen_advances(self):
        pages = {1: self._rows("A", "B"), 2: self._rows("C", "D")}
        # Page 1 (A,B) is entirely seen -> walk on to page 2.
        g = sm.gather_fresh_pages(
            lambda pg: pages.get(pg, []), start_page=1, target=2, is_seen=lambda rows: {"A", "B"}
        )
        assert [r["company_number"] for r in g.rows] == ["C", "D"]
        assert g.pages_walked == 2 and g.skipped_seen == 2

    def test_partial_page_tops_up_from_next(self):
        pages = {1: self._rows("A", "B"), 2: self._rows("C", "D")}
        g = sm.gather_fresh_pages(
            lambda pg: pages.get(pg, []), start_page=1, target=3, is_seen=lambda rows: {"A"}
        )
        assert [r["company_number"] for r in g.rows] == ["B", "C", "D"]
        assert g.pages_walked == 2

    def test_empty_page_stops(self):
        g = sm.gather_fresh_pages(
            lambda pg: self._rows("A") if pg == 1 else [],
            start_page=1,
            target=5,
            is_seen=lambda rows: set(),
        )
        assert [r["company_number"] for r in g.rows] == ["A"] and g.saw_any

    def test_max_pages_caps_the_walk(self):
        calls = []

        def collect(pg):
            calls.append(pg)
            return self._rows("X")  # always the same, always-seen row

        g = sm.gather_fresh_pages(
            collect, start_page=1, target=5, is_seen=lambda rows: {"X"}, max_pages=3
        )
        assert g.rows == [] and len(calls) == 3 and g.skipped_seen == 3


class TestSmearchDedupCli:
    """do_smearch's default action surfaces fresh companies each run (recording
    the ones it outputs); --no-db is a stateless test run."""

    _COMPANIES = [
        {
            "company_number": "C1",
            "company_name": "Alpha Ltd",
            "company_status": "active",
            "company_type": "ltd",
            "date_of_creation": "2020-01-01",
            "sic_codes": ["16100"],
            "registered_office_address": {"locality": "Leeds"},
        },
        {
            "company_number": "C2",
            "company_name": "Bravo Ltd",
            "company_status": "active",
            "company_type": "ltd",
            "date_of_creation": "2020-01-01",
            "sic_codes": ["16100"],
            "registered_office_address": {"locality": "Hull"},
        },
        {
            "company_number": "C3",
            "company_name": "Charlie Ltd",
            "company_status": "active",
            "company_type": "ltd",
            "date_of_creation": "2020-01-01",
            "sic_codes": ["16100"],
            "registered_office_address": {"locality": "York"},
        },
        {
            "company_number": "C4",
            "company_name": "Delta Ltd",
            "company_status": "active",
            "company_type": "ltd",
            "date_of_creation": "2020-01-01",
            "sic_codes": ["16100"],
            "registered_office_address": {"locality": "Hull"},
        },
    ]
    # Distinct account sizes give a stable rank C1>C2>C3>C4 (date/officers equal),
    # independent of the real clock.
    _PROFILES = {
        "C1": {"accounts": {"last_accounts": {"type": "micro-entity"}}},
        "C2": {"accounts": {"last_accounts": {"type": "small"}}},
        "C3": {"accounts": {"last_accounts": {"type": "medium"}}},
        "C4": {"accounts": {"last_accounts": {"type": "full"}}},
    }

    def _router(self):
        def _fake(req, timeout=None):
            url = req.full_url
            if "/advanced-search/" in url:  # page 1 has the companies; later pages are empty
                items = self._COMPANIES if "start_index=0" in url else []
                return _FakeResp({"hits": len(self._COMPANIES), "items": items})
            num = url.split("/company/")[1].split("?")[0].split("/")[0]
            if "/officers" in url:
                return _FakeResp({"active_count": 2})
            return _FakeResp(self._PROFILES.get(num, {}))

        return _fake

    @staticmethod
    def _nums(path):
        with open(path) as f:
            return [r["company_number"] for r in csv.DictReader(f)]

    def test_repeat_runs_surface_fresh_companies(self, tmp_path, monkeypatch, capsys):
        from opencold import cli

        monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "K")
        monkeypatch.delenv("OPENCOLD_SMEARCH_DB", raising=False)  # use isolated CONFIG_DIR
        out = str(tmp_path / "smes.csv")

        with patch("urllib.request.urlopen", side_effect=self._router()):
            cli.do_smearch(
                sic="16100", output=out, top_n=2, enrich=False, use_llm=False, use_expansion=False
            )
            run1 = self._nums(out)
            cli.do_smearch(
                sic="16100", output=out, top_n=2, enrich=False, use_llm=False, use_expansion=False
            )
            run2 = self._nums(out)
            # Third run: every company already enriched -> nothing new, CSV untouched.
            cli.do_smearch(
                sic="16100", output=out, top_n=2, enrich=False, use_llm=False, use_expansion=False
            )
            run3 = self._nums(out)

        assert run1 == ["C1", "C2"]  # top-2 ranked
        assert run2 == ["C3", "C4"]  # the next two -- all different
        assert set(run1).isdisjoint(run2)
        assert run3 == ["C3", "C4"]  # unchanged (nothing fresh written)
        assert "already enriched" in capsys.readouterr().out

    def test_no_db_is_stateless(self, tmp_path, monkeypatch):
        from opencold import cli

        monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "K")
        monkeypatch.delenv("OPENCOLD_SMEARCH_DB", raising=False)
        out = str(tmp_path / "smes.csv")

        with patch("urllib.request.urlopen", side_effect=self._router()):
            cli.do_smearch(
                sic="16100",
                output=out,
                top_n=2,
                enrich=False,
                use_llm=False,
                use_expansion=False,
                no_db=True,
            )
            first = self._nums(out)
            cli.do_smearch(
                sic="16100",
                output=out,
                top_n=2,
                enrich=False,
                use_llm=False,
                use_expansion=False,
                no_db=True,
            )
            second = self._nums(out)

        assert first == ["C1", "C2"] and second == ["C1", "C2"]  # nothing recorded -> same


class TestDormantFilter:
    def test_is_dormant_helper(self):
        assert sm.is_dormant(sm.EnrichedCompany(item={}, account_type="dormant"))
        assert sm.is_dormant(sm.EnrichedCompany(item={}, account_type="DORMANT"))
        assert not sm.is_dormant(sm.EnrichedCompany(item={}, account_type="micro-entity"))
        assert not sm.is_dormant(
            sm.EnrichedCompany(item={}, account_type="")
        )  # new co, not dormant

    @staticmethod
    def _router(search_payload, profiles, officers):
        def _fake(req, timeout=None):
            url = req.full_url
            if "/advanced-search/" in url:
                return _FakeResp(search_payload)
            num = url.split("/company/")[1].split("?")[0].split("/")[0]
            if "/officers" in url:
                return _FakeResp(officers.get(num, {}))
            return _FakeResp(profiles.get(num, {}))

        return _fake

    _SEARCH = {
        "hits": 2,
        "items": [
            {"company_number": "DOR", "company_name": "Sleepy Ltd", "sic_codes": ["10890"]},
            {"company_number": "ACT", "company_name": "Busy Ltd", "sic_codes": ["10890"]},
        ],
    }
    _PROFILES = {
        "DOR": {"accounts": {"last_accounts": {"type": "dormant"}}},
        "ACT": {"accounts": {"last_accounts": {"type": "micro-entity"}}},
    }
    _OFFICERS = {"DOR": {"active_count": 1}, "ACT": {"active_count": 1}}
    _MATCH = [
        sic_match.SicMatch(
            "10890", "Manufacture of other food products n.e.c.", 1.0, ["food"], "manufacture"
        )
    ]

    def test_excludes_dormant_by_default(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=self._router(self._SEARCH, self._PROFILES, self._OFFICERS),
        ):
            rows = sm.collect_smes(self._MATCH, api_key="K", limit=10, this_year=2026)
        names = [r["company_name"] for r in rows]
        assert "Busy Ltd" in names
        assert "Sleepy Ltd" not in names

    def test_keeps_dormant_when_requested(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=self._router(self._SEARCH, self._PROFILES, self._OFFICERS),
        ):
            rows = sm.collect_smes(
                self._MATCH, api_key="K", limit=10, this_year=2026, exclude_dormant=False
            )
        names = [r["company_name"] for r in rows]
        assert "Busy Ltd" in names and "Sleepy Ltd" in names


class TestListActiveOfficers:
    def test_filters_resigned(self):
        payload = {
            "items": [
                {"name": "SMITH, John", "officer_role": "director"},
                {"name": "JONES, Amy", "officer_role": "secretary", "resigned_on": "2020-01-01"},
                {"name": "ACME SECRETARIES LIMITED", "officer_role": "corporate-nominee-secretary"},
            ]
        }
        with patch("urllib.request.urlopen", return_value=_FakeResp(payload)):
            offs = ch.list_active_officers("123", api_key="K")
        assert [o["name"] for o in offs] == ["SMITH, John", "ACME SECRETARIES LIMITED"]


class TestGooglePlaces:
    def test_find_place_headers_and_parse(self):
        captured = {}

        def _fake(req, timeout=None):
            captured["key"] = req.get_header("X-goog-api-key")
            captured["mask"] = req.get_header("X-goog-fieldmask")
            return _FakeResp(
                {
                    "places": [
                        {
                            "displayName": {"text": "Acme Foods"},
                            "formattedAddress": "1 Mill Rd, Leeds",
                            "websiteUri": "https://acmefoods.co.uk",
                            "nationalPhoneNumber": "0113 200 0000",
                            "id": "PLACE1",
                        }
                    ]
                }
            )

        with patch("urllib.request.urlopen", side_effect=_fake):
            p = google_places.find_place("Acme Foods, Leeds", api_key="K")
        assert p["website"] == "https://acmefoods.co.uk"
        assert p["phone"] == "0113 200 0000"
        assert p["name"] == "Acme Foods"
        assert captured["key"] == "K"
        assert "websiteUri" in captured["mask"]

    def test_no_places_returns_none(self):
        with patch("urllib.request.urlopen", return_value=_FakeResp({"places": []})):
            assert google_places.find_place("nothing", api_key="K") is None

    def test_get_key_env_then_missing(self, monkeypatch):
        assert google_places.get_places_key() is None
        monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "PK")
        assert google_places.get_places_key() == "PK"

    def test_google_places_provider_type(self):
        assert "google_places" in config.PROVIDER_TYPES


class TestEnrichHelpers:
    def test_format_officer_name(self):
        assert se._format_officer_name("KOENTOPP, Pauline") == "Pauline Koentopp"
        assert se._format_officer_name("ACME LIMITED") == "Acme Limited"

    def test_address_on_site(self):
        row = {"postal_code": "LS1 1AA", "locality": "Leeds"}
        assert se._address_on_site(row, "Find us at LS1 1AA") == "postcode"
        assert se._address_on_site(row, "We are based in Leeds") == "locality"
        assert se._address_on_site(row, "nothing relevant here") == ""

    def test_csv_fields_in_sync(self):
        assert sm.CSV_FIELDS[-len(se.ENRICH_FIELDS) :] == se.ENRICH_FIELDS


class TestEnrichRow:
    _ROW = {
        "company_name": "Acme Foods Ltd",
        "company_number": "123",
        "address_line_1": "1 Mill Rd",
        "locality": "Leeds",
        "postal_code": "LS1 1AA",
    }

    class _Contacts:
        emails = [("info@acmefoods.co.uk", "https://acmefoods.co.uk")]
        phones = ["+441132000000"]
        address = ""

    class _Page:
        text = "Contact us at our office, LS1 1AA Leeds"

    def test_website_path(self, monkeypatch):
        row = dict(self._ROW)
        monkeypatch.setattr(
            se.ch,
            "list_active_officers",
            lambda number, api_key: [
                {"name": "SMITH, John", "role": "director"},
                {"name": "ACME SECRETARIES LIMITED", "role": "corp"},
            ],
        )
        monkeypatch.setattr(
            se.discovery, "resolve_company_website", lambda name, **k: "https://acmefoods.co.uk"
        )
        monkeypatch.setattr(se.discovery, "normalize_domain", lambda u: "acmefoods.co.uk")
        monkeypatch.setattr(
            se.discovery,
            "extract_company_contacts",
            lambda website, max_pages=4, **kw: self._Contacts(),
        )
        monkeypatch.setattr(
            se.discovery,
            "pick_company_email",
            lambda emails, domain, *a: ("info@acmefoods.co.uk", "role_inbox", emails[0][1]),
        )
        monkeypatch.setattr(
            se.discovery, "crawl_company_pages", lambda website, max_pages=4: [self._Page()]
        )
        out = se.enrich_row(row, ch_key="K")
        assert out["officer_names"] == "John Smith; Acme Secretaries Limited"
        assert out["website"] == "https://acmefoods.co.uk"
        assert out["website_confidence"] == "name+address"
        assert out["phone"] == "+441132000000"
        assert out["email"] == "info@acmefoods.co.uk"
        assert out["address_matched"] == "postcode"
        assert out["contact_source"] == "website"
        assert "officer_linkedin" not in out  # feature removed

    def test_places_fallback(self, monkeypatch):
        row = dict(self._ROW)
        monkeypatch.setattr(se.ch, "list_active_officers", lambda number, api_key: [])
        monkeypatch.setattr(se.discovery, "resolve_company_website", lambda name, **k: None)
        monkeypatch.setattr(
            se.google_places,
            "find_place",
            lambda query, api_key: {
                "phone": "0113 200 0000",
                "website": "",
                "address": "",
                "name": "",
                "id": "",
            },
        )
        out = se.enrich_row(row, ch_key="K", places_key="PK")
        assert out["website"] == ""
        assert out["phone"] == "0113 200 0000"
        assert out["contact_source"] == "google_places"

    def test_no_website_no_places(self, monkeypatch):
        row = dict(self._ROW)
        monkeypatch.setattr(se.ch, "list_active_officers", lambda number, api_key: [])
        monkeypatch.setattr(se.discovery, "resolve_company_website", lambda name, **k: None)
        out = se.enrich_row(row, ch_key="K", places_key=None)
        assert out["website"] == "" and out["phone"] == "" and out["contact_source"] == ""
        assert set(se.ENRICH_FIELDS) <= set(out)  # all enrichment keys present

    def test_llm_rejects_namesake(self, monkeypatch):
        # Address not on site + LLM says wrong company -> website discarded.
        row = dict(self._ROW)
        monkeypatch.setattr(se.ch, "list_active_officers", lambda number, api_key: [])
        monkeypatch.setattr(
            se.discovery, "resolve_company_website", lambda name, **k: "https://wrongco.com"
        )
        monkeypatch.setattr(se.discovery, "normalize_domain", lambda u: "wrongco.com")
        monkeypatch.setattr(
            se.discovery,
            "extract_company_contacts",
            lambda website, max_pages=4, **kw: self._Contacts(),
        )
        monkeypatch.setattr(
            se.discovery,
            "pick_company_email",
            lambda emails, domain, *a: ("x@wrongco.com", "company_email", emails[0][1]),
        )
        monkeypatch.setattr(
            se.discovery,
            "crawl_company_pages",
            lambda website, max_pages=4: [type("P", (), {"text": "unrelated content"})()],
        )
        monkeypatch.setattr(se, "_llm_confirms_website", lambda *a, **k: False)
        out = se.enrich_row(
            row, ch_key="K", use_llm=True, provider={"type": "anthropic", "api_key": "x"}
        )
        assert out["website"] == "" and out["contact_source"] == "" and out["email"] == ""

    def test_llm_confirms_unverified_site(self, monkeypatch):
        # Address not on site but LLM confirms -> kept, confidence tagged +llm.
        row = dict(self._ROW)
        monkeypatch.setattr(se.ch, "list_active_officers", lambda number, api_key: [])
        monkeypatch.setattr(
            se.discovery, "resolve_company_website", lambda name, **k: "https://acmefoods.co.uk"
        )
        monkeypatch.setattr(se.discovery, "normalize_domain", lambda u: "acmefoods.co.uk")
        monkeypatch.setattr(
            se.discovery,
            "extract_company_contacts",
            lambda website, max_pages=4, **kw: self._Contacts(),
        )
        monkeypatch.setattr(
            se.discovery,
            "pick_company_email",
            lambda emails, domain, *a: ("info@acmefoods.co.uk", "role_inbox", emails[0][1]),
        )
        monkeypatch.setattr(
            se.discovery,
            "crawl_company_pages",
            lambda website, max_pages=4: [type("P", (), {"text": "no postcode here"})()],
        )
        monkeypatch.setattr(se, "_llm_confirms_website", lambda *a, **k: True)
        out = se.enrich_row(
            row, ch_key="K", use_llm=True, provider={"type": "anthropic", "api_key": "x"}
        )
        assert out["website"] == "https://acmefoods.co.uk"
        assert out["website_confidence"].endswith("+llm")
        assert out["address_matched"] == ""


class TestReplSmearchParse:
    def test_multiword_icp_is_joined(self):
        # Bug fix: an unquoted multi-word ICP keeps all its words, so the role
        # ("manufacturers") is detected and the picker doesn't fire.
        from opencold.cli import _parse_smearch_args

        args = _parse_smearch_args(["metal", "manufacturers"])
        assert args["icp"] == "metal manufacturers"
        assert sic_match.detect_icp_roles(args["icp"]) == ["manufacture"]

    def test_icp_words_separated_from_options(self):
        from opencold.cli import _parse_smearch_args

        args = _parse_smearch_args(["timber", "merchants", "--top-n", "5", "--no-enrich"])
        assert args["icp"] == "timber merchants"
        assert args["top_n"] == 5 and args["enrich"] is False


class TestFactoryMode:
    def test_is_factory_intent(self):
        assert sic_match.is_factory_intent("food factories")
        assert sic_match.is_factory_intent("metal factory")
        assert not sic_match.is_factory_intent("food manufacturers")
        assert not sic_match.is_factory_intent("plant nursery")
        # "factory" is also a manufacture role -> no picker fires.
        assert sic_match.detect_icp_roles("food factories") == ["manufacture"]

    def test_factory_keywords_and_address(self):
        assert se._factory_keywords("our production facility ships bulk wholesale orders")
        assert not se._factory_keywords("handmade artisan sweets in our little shop")
        assert se._industrial_address(
            {"address_line_2": "Acme Industrial Estate", "locality": "Leeds"}
        )
        assert not se._industrial_address({"address_line_1": "5 High Street", "locality": "Leeds"})

    def test_is_factory_company_paths(self):
        assert se.is_factory_company({"address_line_1": "Unit 2 Trading Estate"}, "")  # address
        assert se.is_factory_company({}, "we run a large production line")  # keyword
        assert not se.is_factory_company({}, "tiny handmade boutique")  # neither
        assert not se.is_factory_company({}, "")  # no content

    def test_factory_account_score_and_size_filter(self):
        assert sm._factory_account_score("small") > sm._factory_account_score("micro-entity")
        assert sm._factory_account_score("micro-entity") > sm._factory_account_score("full")
        assert sm._size_matches("total-exemption-small", ["small"])
        assert sm._size_matches("micro-entity", ["micro"])
        assert not sm._size_matches("micro-entity", ["medium"])

    def test_enrich_top_factories_backfills_past_artisan(self, monkeypatch):
        class _C:
            emails, phones, address = [], [], ""

        pool = [
            {"company_name": "ARTISAN SWEETS LTD", "company_number": "1", "locality": "Leeds"},
            {"company_name": "BIG FOOD FACTORY LTD", "company_number": "2", "locality": "Hull"},
        ]
        texts = {
            "https://artisan.co.uk": "handmade artisan sweets, our little shop",
            "https://big.co.uk": "our 30,000 sq ft production facility, bulk wholesale supply",
        }
        monkeypatch.setattr(se.ch, "list_active_officers", lambda number, api_key: [])
        monkeypatch.setattr(
            se.discovery,
            "resolve_company_website",
            lambda name, **k: f"https://{name.split()[0].lower()}.co.uk",
        )
        monkeypatch.setattr(
            se.discovery, "extract_company_contacts", lambda website, max_pages=4, **kw: _C()
        )
        monkeypatch.setattr(
            se.discovery,
            "crawl_company_pages",
            lambda website, max_pages=4: [type("P", (), {"text": texts.get(website, "")})()],
        )
        kept, scanned = se.enrich_top_factories(pool, target=1, ch_key="K")
        assert scanned == 2  # walked past the artisan
        assert [r["company_name"] for r in kept] == ["BIG FOOD FACTORY LTD"]
