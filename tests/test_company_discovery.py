"""Tests for company-first discovery (ICP + region -> company contact bundle)."""

from unittest.mock import patch

from opencold import discovery
from opencold.discovery import SearchResult, CandidateCompany


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
    def _row(self, region_fit="40", country="United Kingdom (UK)"):
        return {"region_fit": region_fit, "country": country}

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
