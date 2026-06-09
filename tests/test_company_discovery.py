"""Tests for company-first discovery (ICP + region -> company contact bundle)."""

from unittest.mock import patch

import pytest

from opencold import discovery, translator
from opencold.discovery import SearchResult, CandidateCompany


@pytest.fixture(autouse=True)
def _no_translation_network(monkeypatch):
    # Translation is best-effort and network-backed (Lingva). No-op it by default so
    # every test is hermetic regardless of a region's languages; tests that assert
    # translation behaviour re-patch translator.translate inside the test.
    monkeypatch.setattr(translator, "translate", lambda text, target, source="auto": text)


# Bangladesh insurer fixture with rich structured data (the validation target).
GREENDELTA_HTML = """
<html><head>
<script type="application/ld+json">
{"@type":"Organization","name":"Green Delta Insurance",
 "email":"info@greendelta.com.bd","telephone":"+880 2 9676 555",
 "address":{"streetAddress":"Hadi Mansion","addressLocality":"Dhaka","addressCountry":"Bangladesh"},
 "sameAs":["https://www.linkedin.com/company/green-delta-insurance",
           "https://facebook.com/greendelta"]}
</script>
</head><body>
<h1>Green Delta Insurance</h1>
<p>Green Delta provides non-life insurance services across Bangladesh.</p>
<a href="mailto:partnerships@greendelta.com.bd">Partnerships</a>
<a href="tel:+8801711000000">Call us</a>
<a href="/become-a-partner">Become a partner</a>
<footer><a href="https://www.linkedin.com/company/green-delta-insurance">LinkedIn</a></footer>
</body></html>
"""

# Minimal site with only tel:/mailto:/footer-linkedin, no JSON-LD.
PLAIN_HTML = """
<html><body>
<a href="mailto:hello@acme.test">Email</a>
<a href="tel:+1 415 555 0100">Phone</a>
<a href="https://www.linkedin.com/company/acme">LinkedIn</a>
</body></html>
"""


def _fetch_for(host_html: dict):
    """Build a fake enricher._fetch_html keyed by registrable domain."""
    def _fake(url, timeout=None):
        domain = discovery.normalize_domain(url)
        return host_html.get(domain)
    return _fake


class TestContactExtraction:
    def test_jsonld_organization(self):
        with patch("opencold.enricher._fetch_html", _fetch_for({"greendelta.com.bd": GREENDELTA_HTML})):
            c = discovery.extract_company_contacts("https://greendelta.com.bd")
        emails = {e for e, _ in c.emails}
        assert "info@greendelta.com.bd" in emails
        assert "partnerships@greendelta.com.bd" in emails
        assert any(p.startswith("+880") for p in c.phones)
        assert "Dhaka" in c.address
        assert c.linkedin_company_url == "https://www.linkedin.com/company/green-delta-insurance"
        assert c.partnership_url.endswith("/become-a-partner")
        assert c.company_name == "Green Delta Insurance"

    def test_tel_mailto_and_footer_linkedin_without_jsonld(self):
        with patch("opencold.enricher._fetch_html", _fetch_for({"acme.test": PLAIN_HTML})):
            c = discovery.extract_company_contacts("https://acme.test")
        assert ("hello@acme.test", "https://acme.test") in c.emails
        assert any(p.replace(" ", "").startswith("+1") for p in c.phones)
        assert c.linkedin_company_url == "https://www.linkedin.com/company/acme"


class TestEmailPolicy:
    def test_partnerships_beats_info_beats_support(self):
        emails = [
            ("support@acme.test", "u"),
            ("info@acme.test", "u"),
            ("partnerships@acme.test", "u"),
        ]
        email, etype, _ = discovery.pick_company_email(emails, "acme.test")
        assert email == "partnerships@acme.test"
        assert etype == "role_inbox"

    def test_info_is_kept_not_dropped(self):
        # Unlike the person-finder, generic inboxes are valid company contacts.
        email, etype, _ = discovery.pick_company_email([("info@acme.test", "u")], "acme.test")
        assert email == "info@acme.test"
        assert etype == "role_inbox"

    def test_person_email_outranks_role_inbox(self):
        emails = [("info@acme.test", "u"), ("jane.smith@acme.test", "u")]
        email, etype, _ = discovery.pick_company_email(emails, "acme.test")
        assert email == "jane.smith@acme.test"
        assert etype == "person_email"

    def test_off_domain_is_penalized(self):
        emails = [("info@acme.test", "u"), ("partnerships@gmail.com", "u")]
        email, _, _ = discovery.pick_company_email(emails, "acme.test")
        assert email == "info@acme.test"


class TestRegionFit:
    def test_bangladesh_signals_score_high(self):
        c = discovery.CompanyContacts(phones=["+88029676555"], address="Dhaka, Bangladesh")
        score, reasons = discovery.region_fit(c, "https://greendelta.com.bd", "Bangladesh")
        assert score >= 75
        assert "cctld:.bd" in reasons
        assert "phone:+880" in reasons

    def test_foreign_company_scores_low(self):
        c = discovery.CompanyContacts(phones=["+14155550100"], address="San Francisco, USA")
        score, _ = discovery.region_fit(c, "https://acme.com", "Bangladesh")
        assert score == 0

    def test_wrong_country_namesake_flagged_as_conflict(self):
        # "Prime Insurance" exists in both Bangladesh and the UK — a .co.uk match
        # for a Bangladesh search is the wrong company.
        c = discovery.CompanyContacts(phones=["+447549072901"])
        score, reasons = discovery.region_fit(c, "https://primeinsuranceltd.co.uk", "Bangladesh")
        assert score == 0
        assert "region_conflict" in reasons

    def test_region_conflict_ranks_below_in_region(self):
        base = {
            "website_status": "ok", "icp_score": "50", "personalization_score": "60",
            "company_summary": "", "personalization_facts": "",
        }
        in_region, _ = discovery._score_company_lead(dict(base), 60, "role_inbox", region_targeted=True)
        conflict, reasons = discovery._score_company_lead(
            dict(base), 0, "role_inbox", region_targeted=True, region_conflict=True
        )
        assert conflict < in_region
        assert "region_conflict" in reasons

    def test_foreign_address_beats_target_pagetext(self):
        # Cameroon exporter with an SEO page targeting Turkey: the stated address wins.
        c = discovery.CompanyContacts(
            phones=["+237671776559"],
            address="1310 Avenue De Gaulle, Douala, BP 2667, Cameroon")
        score, reasons = discovery.region_fit(
            c, "https://cameroontimberexport.com", "Turkey",
            pages_text="timber wood supplier turkey best prices")
        assert score == 0
        assert "addr_region_match" not in reasons
        assert "region_conflict:addr:cameroon" in reasons

    def test_uk_address_flags_conflict_for_turkey(self):
        c = discovery.CompanyContacts(
            phones=["+442071935609"],
            address="59 St Martin's Lane, London, WC2N 4JS, United Kingdom")
        _, reasons = discovery.region_fit(
            c, "https://wknightconsulting.com", "Turkey",
            pages_text="UK-based timber wood supplier serving turkey")
        assert "region_conflict" in reasons

    def test_page_text_target_is_not_an_anchor(self):
        # A marketplace whose page lists "companies from turkey" is not anchored there.
        c = discovery.CompanyContacts()
        score, reasons = discovery.region_fit(
            c, "https://fordaq.com", "Turkey",
            pages_text="companies from turkey timber marketplace")
        assert score == 0
        assert "addr_region_match" not in reasons
        assert "page_region_mention" in reasons
        assert "region_conflict" not in reasons

    def test_genuine_local_with_turkish_city_anchors(self):
        c = discovery.CompanyContacts(phones=["+902120000000"], address="Istanbul, Turkey")
        score, reasons = discovery.region_fit(c, "https://example.com", "Turkey")
        assert score >= 60
        assert "addr_region_match" in reasons
        assert "region_conflict" not in reasons

    def test_local_with_foreign_sales_phone_not_rejected(self):
        c = discovery.CompanyContacts(phones=["+902120000000", "+442079460000"], address="Bursa, Turkey")
        _, reasons = discovery.region_fit(c, "https://example.com.tr", "Turkey")
        assert "region_conflict" not in reasons

    def test_hq_prose_anchors_thin_local_site(self):
        c = discovery.CompanyContacts()
        score, reasons = discovery.region_fit(
            c, "https://anatoliawood.com", "Turkey",
            pages_text="An Istanbul-based timber mill since 1990.")
        assert "hq_region_match" in reasons
        assert score >= 20

    def test_foreign_hq_prose_rejected_when_no_anchor(self):
        c = discovery.CompanyContacts()
        _, reasons = discovery.region_fit(
            c, "https://acme.com", "Turkey",
            pages_text="We are headquartered in Douala, Cameroon.")
        assert "region_conflict:hq:cameroon" in reasons

    def test_customer_market_prose_not_treated_as_hq(self):
        c = discovery.CompanyContacts()
        _, reasons = discovery.region_fit(
            c, "https://acme.com", "Turkey",
            pages_text="We supply companies based in Germany.")
        assert "region_conflict" not in reasons

    def test_foreign_same_language_company_rejected(self):
        # A French company surfacing in a French-language Morocco search must be
        # rejected, not verified — even though it shares the search language. Each
        # foreign signal (ccTLD, stated country, dialing code) trips the conflict.
        for site, addr, phone in [
            ("https://recyclage-paris.fr", "Paris, France", "+33142000000"),
            ("https://dechets.com", "Lyon, France", "+33478000000"),
            ("https://acme.com", "", "+33100000000"),
        ]:
            c = discovery.CompanyContacts(phones=[phone], address=addr)
            score, reasons = discovery.region_fit(c, site, "Morocco")
            assert score == 0, site
            assert "region_conflict" in reasons, site

    def test_local_company_on_shared_language_still_verifies(self):
        # A genuine Moroccan firm (French-language site) keeps its local anchors.
        c = discovery.CompanyContacts(phones=["+212522000000"], address="Casablanca, Morocco")
        score, reasons = discovery.region_fit(c, "https://recyclage.ma", "Morocco")
        assert score >= 60
        assert "region_conflict" not in reasons


class TestLlmSeeding:
    def test_parse_json_object_tolerates_fences(self):
        data = discovery._parse_json_object('```json\n{"companies": ["A", "B"]}\n```')
        assert data["companies"] == ["A", "B"]

    def test_seed_parses_companies_and_directories(self):
        payload = (
            '{"companies": ["Green Delta Insurance", "Pragati Insurance", "Green Delta Insurance"], '
            '"local_directories": ["IDRA licensed insurers"]}'
        )
        with patch("opencold.generator.complete", return_value=payload):
            seed = discovery.seed_companies_via_llm(
                "insurance companies", "Bangladesh",
                provider_config={"type": "anthropic", "api_key": "x"},
            )
        assert seed["companies"] == ["Green Delta Insurance", "Pragati Insurance"]  # deduped
        assert seed["local_directories"] == ["IDRA licensed insurers"]

    def test_seed_without_provider_returns_empty(self):
        with patch("opencold.discovery._resolve_llm_provider", return_value=None):
            seed = discovery.seed_companies_via_llm("x", "y")
        assert seed == {"companies": [], "local_directories": []}


class TestCandidateHarvest:
    def test_dedup_and_directory_filtering(self):
        results = [
            SearchResult(title="Green Delta", url="https://greendelta.com.bd/about"),
            SearchResult(title="Green Delta", url="https://www.greendelta.com.bd/"),  # same domain
            SearchResult(title="Crunchbase", url="https://www.crunchbase.com/org/x"),  # directory
            SearchResult(title="LinkedIn", url="https://www.linkedin.com/company/x"),  # blocked
        ]
        with patch("opencold.discovery._resolve_llm_provider", return_value=None), \
             patch("opencold.discovery.web_search", return_value=results):
            cands = discovery.discover_company_candidates("insurance", "Bangladesh", limit=10)
        domains = {discovery.normalize_domain(c.website) for c in cands}
        assert domains == {"greendelta.com.bd"}
        assert cands[0].discovery_channel == "search"


class TestEndToEnd:
    def test_company_rows_keep_no_email_rows_and_emit_columns(self):
        candidates = [
            CandidateCompany("Green Delta Insurance", "https://greendelta.com.bd", "src", "search", "search"),
            CandidateCompany("No Email Co", "https://noemailco.test", "src", "search", "search"),
        ]
        html_by_domain = {
            "greendelta.com.bd": GREENDELTA_HTML,
            "noemailco.test": "<html><body><h1>No Email Co</h1><p>We do insurance things.</p></body></html>",
        }
        with patch("opencold.discovery.discover_company_candidates", return_value=candidates), \
             patch("opencold.discovery.web_search", return_value=[]), \
             patch("opencold.icp_expansion.expand_icp", return_value=set()), \
             patch("opencold.enricher._fetch_html", _fetch_for(html_by_domain)):
            rows = discovery.discover_company_rows(
                "insurance companies", "Bangladesh", limit=10, use_llm=False,
            )

        assert len(rows) == 2
        by_company = {r["company"]: r for r in rows}

        gd = by_company["Green Delta Insurance"]
        assert gd["email"] == "partnerships@greendelta.com.bd"
        assert gd["region_fit"] == "100"
        assert gd["linkedin_company_url"].endswith("/green-delta-insurance")
        assert gd["partnership_channel"].startswith("page:")

        # No-email companies survive (still valuable: phone / LinkedIn / address).
        ne = by_company["No Email Co"]
        assert ne["email"] == ""

        # Every row carries the full company schema.
        for row in rows:
            for col in discovery.COMPANY_CSV_FIELDS:
                assert col in row, f"missing column {col}"

    def test_find_people_adds_contact_columns(self):
        company = CandidateCompany("Acme", "https://acme.test", "src", "search", "search")
        with patch("opencold.discovery.web_search", return_value=[]), \
             patch("opencold.enricher._fetch_html", _fetch_for({"acme.test": PLAIN_HTML})):
            row = discovery.build_company_row(company, "saas", "USA", find_people=True)
        for col in discovery.COMPANY_PEOPLE_FIELDS:
            assert col in row


class TestWebsiteResolution:
    def test_second_level_cctld_not_collapsed(self):
        # jbc.gov.bd must stay jbc.gov.bd, not collapse to the gov.bd public suffix.
        assert discovery.normalize_domain("https://jbc.gov.bd/contact") == "jbc.gov.bd"
        assert discovery.normalize_domain("https://www.greendelta.com.bd") == "greendelta.com.bd"
        assert discovery.normalize_domain("https://news.example.ac.uk") == "example.ac.uk"

    def test_require_match_rejects_non_matching_domain(self):
        # A media article about the company must not become its website.
        results = [SearchResult(title="Profile", url="https://futurestartup.com/profile/green-delta")]
        with patch("opencold.discovery.web_search", return_value=results):
            strict = discovery.resolve_company_website("Green Delta Insurance", require_match=True)
            loose = discovery.resolve_company_website("Green Delta Insurance")
        assert strict is None
        assert loose == "https://futurestartup.com"  # default keeps the fallback

    def test_require_match_accepts_real_domain(self):
        results = [SearchResult(title="Green Delta", url="https://green-delta.com/")]
        with patch("opencold.discovery.web_search", return_value=results):
            assert discovery.resolve_company_website("Green Delta Insurance", require_match=True) == "https://green-delta.com"


class TestRegionParsing:
    def test_resolve_region_key_handles_freeform(self):
        assert discovery._resolve_region_key("United Kingdom (UK)") == "united kingdom"
        assert discovery._resolve_region_key("uk") == "united kingdom"
        assert discovery._resolve_region_key("England") == "united kingdom"
        assert discovery._resolve_region_key("Bangladesh") == "bangladesh"

    def test_region_fit_fires_for_freeform_uk(self):
        # Regression: "United Kingdom (UK)" used to yield region_fit=0 for every row.
        c = discovery.CompanyContacts(phones=["+441296662439"], address="London")
        score, reasons = discovery.region_fit(c, "https://bowleswyer.co.uk", "United Kingdom (UK)")
        assert score >= 40
        assert "cctld:.uk" in reasons


class TestIcpEvidence:
    def test_evidence_is_content_only(self):
        assert discovery._icp_evidence("landscape", {"company_summary": "garden & landscape design", "personalization_facts": ""})
        assert not discovery._icp_evidence("landscape", {"company_summary": "satellite IoT tracking devices", "personalization_facts": ""})

    def test_score_company_no_longer_constant(self):
        # Regression: discovery_reason echoed the ICP, making every score identical.
        cand = discovery.CandidateCompany("Ground Control", "https://groundcontrol.com", "u", "llm seed: landscape in UK", "llm")
        iot = {"website_status": "ok", "company_summary": "satellite IoT tracking devices", "personalization_facts": ""}
        land = {"website_status": "ok", "company_summary": "commercial landscape & grounds maintenance", "personalization_facts": ""}
        assert discovery.score_company(cand, land, "landscape")[0] > discovery.score_company(cand, iot, "landscape")[0]


class TestMorphology:
    def test_stem_collapses_inflections(self):
        stems = {discovery._stem(w) for w in ["landscape", "landscaping", "landscaper", "landscapes", "landscaped"]}
        assert stems == {"landscap"}

    def test_evidence_matches_morphological_variant(self):
        # The recall fix: 'landscape' must be evidenced by content that only says 'landscaping'.
        assert discovery._icp_evidence("landscape companies", {"company_summary": "expert design and landscaping", "personalization_facts": ""})
        assert discovery._icp_evidence("plumbing", {"company_summary": "experienced plumber and heating", "personalization_facts": ""})

    def test_no_evidence_for_unrelated_or_short_collisions(self):
        # Unrelated industry stays out; conservative stemmer avoids care->car / marine~marina.
        assert not discovery._icp_evidence("landscape companies", {"company_summary": "satellite IoT tracking devices", "personalization_facts": ""})
        assert not discovery._icp_match({"marine"}, "luxury marina apartments")
        assert not discovery._icp_match({"care"}, "a caring local team")

    def test_substring_backcompat_preserved(self):
        # Old literal-substring matches still hold (compound words).
        assert discovery._icp_match({"tech"}, "a fintech and biotech platform") == ["tech"]


class TestResolutionContext:
    def test_prefer_cc_picks_country_domain(self):
        # Two same-name domains: the UK ccTLD one must win for a UK search.
        results = [
            SearchResult(title="Ground Control", url="https://groundcontrol.com"),
            SearchResult(title="Ground Control", url="https://groundcontrol.co.uk"),
        ]
        with patch("opencold.discovery.web_search", return_value=results):
            url = discovery.resolve_company_website(
                "Ground Control", require_match=True, context="landscape United Kingdom", prefer_cc="uk",
            )
        assert url == "https://groundcontrol.co.uk"


class TestClassification:
    def _row(self, region_fit="40", country="United Kingdom (UK)", region_anchor=None,
             is_aggregator=False, is_government=False):
        anchor = (int(region_fit) > 0) if region_anchor is None else region_anchor
        return {"region_fit": region_fit, "country": country, "_region_anchor": anchor,
                "_is_aggregator": is_aggregator, "_is_government": is_government}

    def test_region_conflict_is_rejected(self):
        conf, _ = discovery._classify_company(self._row(region_fit="0"), True, True, None)
        assert conf == "rejected"

    def test_llm_no_is_rejected(self):
        conf, _ = discovery._classify_company(self._row(), True, False, {"match": "no", "industry": "IoT"})
        assert conf == "rejected"

    def test_icp_and_region_confirmed_is_verified(self):
        conf, _ = discovery._classify_company(self._row(), True, False, None)
        assert conf == "verified"

    def test_llm_unknown_defers_to_deterministic(self):
        # Model doesn't know -> fall back to deterministic (region 0 -> review, not reject).
        conf, _ = discovery._classify_company(self._row(region_fit="0"), True, False, {"match": "unknown", "country": ""})
        assert conf == "review"

    def test_llm_country_can_confirm_region(self):
        # .com UK company with region_fit 0 gets rescued by the judge's country read.
        conf, _ = discovery._classify_company(
            self._row(region_fit="0"), True, False, {"match": "yes", "country": "United Kingdom"}
        )
        assert conf == "verified"

    def test_no_icp_evidence_is_review(self):
        conf, _ = discovery._classify_company(self._row(), False, False, {"match": "unknown"})
        assert conf == "review"

    def test_no_region_anchor_is_review(self):
        # A target mention only in marketing text confers no anchor -> not verified.
        conf, why = discovery._classify_company(
            self._row(region_fit="0", region_anchor=False), True, False, None)
        assert conf == "review"
        assert why == "region_unconfirmed"

    def test_government_site_is_rejected(self):
        conf, why = discovery._classify_company(self._row(is_government=True), True, False, None)
        assert conf == "rejected"
        assert why == "government_site"

    def test_aggregator_routed_to_review(self):
        conf, why = discovery._classify_company(self._row(is_aggregator=True), True, False, None)
        assert conf == "review"
        assert why == "marketplace_directory"


class TestCountryDetection:
    def test_address_country_by_name(self):
        assert discovery._detect_address_country("..., Douala, Cameroon") == "cameroon"
        assert discovery._detect_address_country("..., London, United Kingdom") == "united kingdom"

    def test_address_prefers_unambiguous(self):
        # US state Georgia must not be read as Georgia-the-country.
        assert discovery._detect_address_country("Atlanta, Georgia, USA") == "united states"

    def test_address_demonym(self):
        assert discovery._detect_address_country("a UK-based supplier") == "united kingdom"

    def test_address_none(self):
        assert discovery._detect_address_country("123 Main Street, Suite 4") is None

    def test_phone_country_longest_prefix(self):
        assert discovery._detect_phone_country("+237671776559") == "cameroon"
        assert discovery._detect_phone_country("+447549072901") == "united kingdom"
        assert discovery._detect_phone_country("+902120000000") == "turkey"
        assert discovery._detect_phone_country("01234") is None


class TestDomainCountry:
    def test_unambiguous_country_in_label(self):
        assert discovery._detect_domain_country("cameroontimberexport.com") == "cameroon"
        assert discovery._detect_domain_country("germany-timber.com") == "germany"

    def test_ambiguous_name_ignored(self):
        assert discovery._detect_domain_country("jordanlumber.com") is None

    def test_generic_tld_label_not_matched(self):
        assert discovery._detect_domain_country("acme.io") is None

    def test_short_name_substring_not_matched(self):
        # 'oman' (len<5) must not match inside an unrelated label.
        assert discovery._detect_domain_country("womanswear.com") is None


class TestProseLocation:
    def test_adjective_form(self):
        assert discovery._detect_prose_location("a UK-based timber supplier") == "united kingdom"
        assert discovery._detect_prose_location("an Istanbul-based mill") == "turkey"

    def test_verb_form_city_to_region(self):
        assert discovery._detect_prose_location("We are headquartered in Douala, Cameroon") == "cameroon"

    def test_customer_subject_excluded(self):
        assert discovery._detect_prose_location("serving customers based in Turkey") is None
        assert discovery._detect_prose_location("we supply companies based in Germany") is None

    def test_no_hq_idiom(self):
        assert discovery._detect_prose_location("top timber supplier turkey best prices") is None


class TestAggregator:
    def test_known_stem(self):
        assert discovery._is_aggregator("fordaq.com")
        assert discovery._is_aggregator("europages.com.tr")  # ccTLD variant via stem

    def test_summary_keyword(self):
        assert discovery._is_aggregator("acme.com", "the leading b2b marketplace for timber")

    def test_real_company_not_flagged(self):
        assert not discovery._is_aggregator("acme.com", "family-owned timber mill since 1960")

    def test_local_directories_flagged(self):
        # Moroccan yellow pages / directories that slipped through as "verified"
        assert discovery._is_aggregator("telecontact.ma")
        assert discovery._is_aggregator("kerix.net")
        assert discovery._is_aggregator("goafricaonline.com")

    def test_native_directory_phrasing(self):
        assert discovery._is_aggregator("acme.ma", "l'annuaire des professionnels du Maroc")
        assert discovery._is_aggregator("acme.com", "the directory of professionals in Morocco")
        assert discovery._is_aggregator("acme.com", "your local yellow pages for businesses")


class TestPhoneCleaning:
    def test_real_numbers_kept(self):
        assert discovery._clean_phone("+212 522 66 28 37") == "+212522662837"
        assert discovery._clean_phone("05 22 77 71 00") == "0522777100"

    def test_year_spans_rejected(self):
        # Copyright lines ("2005-2026") and programme ranges ("2021-2030")
        # regex-match as phones but are not.
        assert discovery._clean_phone("2005-2026") == ""
        assert discovery._clean_phone("2021 2030") == ""

    def test_doubled_quad_rejected(self):
        assert discovery._clean_phone("1000 1000") == ""

    def test_plus_prefix_trusted(self):
        assert discovery._clean_phone("+20212030") == "+20212030"


class TestLinkedinSlugMatch:
    def test_matching_slugs_accepted(self):
        assert discovery._linkedin_slug_matches(
            "https://www.linkedin.com/company/valotrimaroc", "Valotri", "valotri.com")
        assert discovery._linkedin_slug_matches(
            "https://www.linkedin.com/company/tadweir-maroc", "Tadweir", "tadweir.com")

    def test_unrelated_slug_rejected(self):
        assert not discovery._linkedin_slug_matches(
            "https://www.linkedin.com/company/cotiviti", "Macarpa", "macarpa.com")
        assert not discovery._linkedin_slug_matches(
            "https://www.linkedin.com/company/suez", "Metalimpex group", "metalimpexgroup.com")

    def test_tiny_slug_rejected(self):
        assert not discovery._linkedin_slug_matches(
            "https://www.linkedin.com/company/t", "Telecontact", "telecontact.ma")


class TestGovernment:
    def test_gov_and_mil(self):
        assert discovery._is_government_domain("michigan.gov")
        assert discovery._is_government_domain("x.gov.tr")
        assert discovery._is_government_domain("army.mil")

    def test_company_not_flagged(self):
        assert not discovery._is_government_domain("acme.com")
        assert not discovery._is_government_domain("governance.com")


class TestJudge:
    def test_judge_parses_grounded_results(self):
        rows = [{"company": "Acme", "website": "https://acme.test", "company_summary": "insurance in the UK", "personalization_facts": ""}]
        payload = '{"results":[{"i":0,"match":"yes","industry":"insurance","country":"United Kingdom","evidence":"insurance in the UK"}]}'
        with patch("opencold.generator.complete", return_value=payload):
            out = discovery.judge_companies(rows, "insurance", "United Kingdom", {"type": "anthropic", "api_key": "x"})
        assert out[0]["match"] == "yes"
        assert out[0]["country"] == "United Kingdom"


class TestWall:
    def test_wall_drawn_between_verified_and_review(self, tmp_path):
        rows = [
            {**{c: "" for c in discovery.COMPANY_CSV_FIELDS}, "company": "GoodCo", "match_confidence": "verified"},
            {**{c: "" for c in discovery.COMPANY_CSV_FIELDS}, "company": "MaybeCo", "match_confidence": "review"},
        ]
        out = tmp_path / "o.csv"
        discovery.write_company_csv(rows, str(out))
        text = out.read_text(encoding="utf-8")
        assert discovery.WALL_BANNER in text
        assert text.index("GoodCo") < text.index(discovery.WALL_BANNER) < text.index("MaybeCo")

    def test_read_csv_skips_wall_rows(self, tmp_path):
        from opencold import cli
        p = tmp_path / "leads.csv"
        p.write_text(
            "name,company,email\n"
            ",GoodCo,info@good.test\n"
            ",,\n"
            f",{discovery.WALL_BANNER},\n"
            ",MaybeCo,info@maybe.test\n",
            encoding="utf-8",
        )
        rows = cli._read_csv(str(p), require_email=False)
        assert [r["company"] for r in rows] == ["GoodCo", "MaybeCo"]


class TestCsvWriter:
    def test_header_and_optional_people_columns(self, tmp_path):
        rows = [{c: "" for c in discovery.COMPANY_CSV_FIELDS}]
        rows[0]["company"] = "Acme"
        out = tmp_path / "out.csv"
        discovery.write_company_csv(rows, str(out))
        header = out.read_text(encoding="utf-8").splitlines()[0]
        assert header.split(",")[:4] == ["email", "name", "company", "website"]
        assert "region_fit" in header
        assert "contact_name" not in header  # no people columns unless present

        rows[0]["contact_name"] = "Jane Doe"
        discovery.write_company_csv(rows, str(out))
        header2 = out.read_text(encoding="utf-8").splitlines()[0]
        assert "contact_name" in header2


# Real-world layout: {{columns-list}} bullets, mostly UNlinked, with sections to skip.
WIKI_BULLETS = """{{short description|none}}

== Private sector (life) ==
{{columns-list|colwidth=20em|
* [[Pragati Life Insurance|Pragati Life Insurance Ltd.]]
* Green Delta Insurance Company Ltd.
* Guardian Life Insurance Company Ltd. (PLC)
}}

== Defunct ==
* Old Failed Insurance Ltd

== Regulators ==
* Insurance Development and Regulatory Authority

== See also ==
* [[Economy of Bangladesh]]
"""

# Table layout with header row + a styled cell attribute.
WIKI_TABLE = """== Banks ==
{| class="wikitable"
|-
! Name !! Founded
|-
| [[Delta Bank]] || 1990
|-
| style="text-align:left" | Epsilon Bank PLC || 2001
|}
"""


class TestWikipediaParser:
    def test_bullets_skip_sections_and_clean_names(self):
        names = discovery._parse_wikitext_names(WIKI_BULLETS)
        # Trailing periods stripped; [[wikilink|text]] resolved to text.
        assert "Pragati Life Insurance Ltd" in names
        assert "Green Delta Insurance Company Ltd" in names
        assert "Guardian Life Insurance Company Ltd" in names  # (PLC) stripped
        # Defunct / Regulators / See also entries are excluded.
        assert all("Old Failed" not in n for n in names)
        assert all("Regulatory Authority" not in n for n in names)
        assert all("Economy of" not in n for n in names)

    def test_wikitable_first_column(self):
        names = discovery._parse_wikitext_names(WIKI_TABLE)
        assert names == ["Delta Bank", "Epsilon Bank PLC"]

    def test_clean_wiki_name_strips_markup_and_descriptions(self):
        assert discovery._clean_wiki_name("[[Foo|Foo Bar Ltd]] – the best (est 1990)<ref>x</ref>") == "Foo Bar Ltd"
        assert discovery._clean_wiki_name("'''Acme'''") == "Acme"
        # Intra-name hyphen preserved (only spaced dashes split).
        assert discovery._clean_wiki_name("Bradley-Hole Schoenaich") == "Bradley-Hole Schoenaich"

    def test_blocklist_excludes_non_companies(self):
        assert discovery._parse_wikitext_names("* Securities and Exchange Commission") == []


class TestWikipediaChannel:
    def test_company_names_from_list_page(self):
        search = {"query": {"search": [{"title": "List of insurance companies in Bangladesh"}]}}
        parse = {"parse": {"wikitext": {"*": WIKI_BULLETS}}}

        def fake_api(params):
            return search if params.get("list") == "search" else parse

        with patch("opencold.discovery._wiki_api_get", side_effect=fake_api):
            out = discovery.wikipedia_company_names("insurance companies", "Bangladesh")
        names = [n for n, _ in out]
        assert "Green Delta Insurance Company Ltd" in names
        assert all(src.startswith("https://en.wikipedia.org/wiki/") for _, src in out)

    def test_list_titles_filters_to_list_pages(self):
        search = {"query": {"search": [
            {"title": "List of insurance companies in Bangladesh"},
            {"title": "MetLife"},  # not a list page -> dropped
        ]}}
        with patch("opencold.discovery._wiki_api_get", return_value=search):
            titles = discovery.wikipedia_list_titles("insurance companies", "Bangladesh")
        assert titles == ["List of insurance companies in Bangladesh"]

    def test_channel_is_additive_and_tagged(self):
        # Wikipedia contributes a candidate; search harvest still runs alongside.
        with patch("opencold.discovery.wikipedia_company_names",
                   return_value=[("Green Delta Insurance", "https://en.wikipedia.org/wiki/List")]), \
             patch("opencold.discovery._resolve_names",
                   return_value=[("Green Delta Insurance", "https://greendelta.com.bd")]), \
             patch("opencold.discovery.discover_companies_by_query",
                   return_value=[CandidateCompany("Other Co", "https://other.test", "u", "search")]):
            cands = discovery.discover_company_candidates(
                "insurance companies", "Bangladesh", use_llm=False, use_wiki=True,
            )
        by_channel = {c.discovery_channel for c in cands}
        assert "wikipedia" in by_channel and "search" in by_channel

    def test_no_wiki_disables_channel(self):
        with patch("opencold.discovery.wikipedia_company_names") as wiki, \
             patch("opencold.discovery.discover_companies_by_query", return_value=[]):
            discovery.discover_company_candidates(
                "insurance companies", "Bangladesh", use_llm=False, use_wiki=False,
            )
        wiki.assert_not_called()


class TestTranslation:
    def test_region_language_maps_local_languages_only(self):
        assert discovery._region_language("Türkiye") == "tr"
        assert discovery._region_language("turkey") == "tr"
        assert discovery._region_language("Germany") == "de"
        # English-business regions stay English (None) -> translation no-ops.
        assert discovery._region_language("United Kingdom") is None
        assert discovery._region_language("USA") is None

    def test_region_languages_multilingual(self):
        assert discovery._region_languages("Morocco") == ["fr", "ar"]
        assert discovery._region_languages("Switzerland") == ["de", "fr", "it"]
        assert discovery._region_languages("Belgium") == ["nl", "fr"]
        assert discovery._region_languages("China") == ["zh"]    # derived (was dropped by a stale literal)
        assert discovery._region_languages("United Kingdom") == []
        assert discovery._region_languages("USA") == []

    def test_native_queries_for_each_language(self):
        captured = []

        def fake_search(query, num=10):
            captured.append(query)
            return []

        def fake_translate(text, target, source="auto"):
            return f"{text} ::{target}"

        with patch("opencold.translator.translate", side_effect=fake_translate), \
             patch("opencold.discovery.web_search", side_effect=fake_search):
            discovery.discover_companies_by_query("recycling", "Morocco", limit=50,
                                                  target_langs=["fr", "ar"])
        assert any(q.endswith("::fr") for q in captured)                 # French searched
        assert any(q.endswith("::ar") for q in captured)                 # Arabic searched
        assert any("Morocco" in q and "::" not in q for q in captured)   # English kept

    def test_native_queries_appended_for_translatable_region(self):
        captured = []

        def fake_search(query, num=10):
            captured.append(query)
            return []

        def fake_translate(text, target, source="auto"):
            return f"{text} ::{target}"

        with patch("opencold.translator.translate", side_effect=fake_translate), \
             patch("opencold.discovery.web_search", side_effect=fake_search):
            discovery.discover_companies_by_query("timber", "Turkey", limit=50, target_langs=["tr"])

        assert "timber companies in Turkey" in captured       # English kept
        assert any(q.endswith("::tr") for q in captured)       # native added

    def test_no_native_queries_without_target_lang(self):
        captured = []

        def fake_search(query, num=10):
            captured.append(query)
            return []

        with patch("opencold.translator.translate", side_effect=AssertionError("must not translate")), \
             patch("opencold.discovery.web_search", side_effect=fake_search):
            discovery.discover_companies_by_query("timber", "Turkey", limit=50, target_langs=None)

        assert captured == discovery.region_query_templates("timber", "Turkey")

    def test_native_terms_evidence_home_language_site(self):
        enrichment = {"company_summary": "kaliteli kereste tedariki", "personalization_facts": ""}
        # English ICP misses a Turkish-only site...
        assert not discovery._icp_evidence("timber", enrichment)
        # ...but the native term rescues it without translating the page.
        assert discovery._icp_evidence("timber", enrichment, {"kereste"})

    def test_translate_icp_terms_keeps_unicode_tokens(self):
        def fake_translate(text, target, source="auto"):
            return "orman ürünleri" if text == "timber" else text

        with patch("opencold.translator.translate", side_effect=fake_translate):
            terms = discovery._translate_icp_terms("timber", "tr")
        assert "orman" in terms and "ürünleri" in terms

    def test_translate_terms_drops_function_words(self):
        # "waste management" -> "gestion des déchets": the article "des" matches ANY
        # French text, so it must never become a matcher term (it made Moroccan
        # directories "verified" for a Recycling ICP). The full phrase is kept.
        def fake_translate(text, target, source="auto"):
            return "gestion des déchets" if text == "waste management" else text

        with patch("opencold.translator.translate", side_effect=fake_translate):
            terms = discovery._translate_terms({"waste management"}, "fr")
        assert "des" not in terms
        assert "déchets" in terms
        assert "gestion des déchets" in terms

    def test_translate_terms_rejects_wrong_roundtrip(self):
        # MyMemory returns a wrong translation-memory match for recycling->ar
        # ("water treatment", match=0.99). The round trip exposes it.
        def fake_translate(text, target, source="auto"):
            if text == "recycling" and target == "ar":
                return "معالجة المياه"
            if text == "معالجة المياه" and target == "en":
                return "water treatment"
            return text

        with patch("opencold.translator.translate", side_effect=fake_translate):
            assert discovery._translate_terms({"recycling"}, "ar") == set()

    def test_translate_terms_roundtrip_unavailable_keeps_term(self):
        def fake_translate(text, target, source="auto"):
            if text == "recycling" and target == "fr":
                return "recyclage"
            return text  # back-translation echoes input (provider down)

        with patch("opencold.translator.translate", side_effect=fake_translate):
            assert discovery._translate_terms({"recycling"}, "fr") == {"recyclage"}

    def test_translate_terms_collapses_alternative_lists(self):
        # Providers sometimes return every alternative slash-separated.
        def fake_translate(text, target, source="auto"):
            if text == "waste" and target == "fr":
                return "gaspillage/gaspiller /perdre /gâcher / déchet/déchets/tricher"
            if target == "en":
                return "wastage"
            return text

        with patch("opencold.translator.translate", side_effect=fake_translate):
            terms = discovery._translate_terms({"waste"}, "fr")
        # Only the first alternative is considered; generic verbs never leak in.
        assert "tricher" not in terms and "perdre" not in terms

    def test_weak_only_evidence_needs_two_matches(self):
        # One half-weight expansion hit is not verification-grade evidence...
        thin = {"company_summary": "annuaire des professionnels du Maroc", "personalization_facts": ""}
        assert not discovery._icp_evidence("recycling", thin, set(), {"gestion", "valorisation"})
        # ...two weak hits are, and one strong (ICP/native) hit always is.
        real = {"company_summary": "collecte et valorisation, gestion des déchets", "personalization_facts": ""}
        assert discovery._icp_evidence("recycling", real, set(), {"gestion", "valorisation"})
        assert discovery._icp_evidence("recycling", thin, {"annuaire"}, set()) is True

    def test_localize_translates_facts_on_english_miss(self):
        enrichment = {
            "company_summary": "kaliteli kereste ve tomruk tedariki",
            "personalization_facts": "kaliteli kereste ve tomruk tedariki",
        }

        def fake_translate(text, target, source="auto"):
            return "quality timber and log supply"

        with patch("opencold.translator.translate", side_effect=fake_translate):
            out = discovery._localize_enrichment(enrichment, "timber", set())
        assert "timber" in out["company_summary"].lower()
        assert discovery._icp_evidence("timber", out)

    def test_localize_is_noop_when_evidence_present(self):
        enrichment = {"company_summary": "premium timber supplier", "personalization_facts": ""}
        with patch("opencold.translator.translate") as tr:
            out = discovery._localize_enrichment(enrichment, "timber", set())
        tr.assert_not_called()      # already-English sites cost no translation
        assert out == enrichment
