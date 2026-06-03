"""Tests for public source lead discovery."""

from unittest.mock import patch

from opencold import discovery, enricher


SOURCE_HTML = """
<html><body>
  <a href="https://acme.dev">Acme DevTools</a>
  <a href="https://linear.app">Linear</a>
  <a href="https://twitter.com/acme">Twitter</a>
  <a href="/internal">Internal link</a>
</body></html>
"""

COMPANY_PAGE = enricher.PageContent(
    url="https://acme.dev",
    title="Acme DevTools",
    description="Acme helps engineering teams automate release workflows.",
    text="Contact Ada Lovelace at ada@acme.dev for partnerships.",
)


class TestExtractCompanies:
    def test_extracts_external_company_links(self):
        companies = discovery.extract_companies_from_html(SOURCE_HTML, "https://source.test/list")
        websites = {c.website for c in companies}

        assert "https://acme.dev" in websites
        assert "https://linear.app" in websites
        assert "https://twitter.com" not in websites
        assert all(c.discovery_source_url == "https://source.test/list" for c in companies)

    def test_normalizes_domain(self):
        assert discovery.normalize_domain("https://www.example.co.uk/path") == "example.co.uk"

    def test_cta_anchor_uses_domain_name(self):
        html = '<a href="https://freshworks.com">Visit →</a>'
        companies = discovery.extract_companies_from_html(html, "https://source.test")
        assert companies[0].company == "Freshworks"


class TestContacts:
    def test_finds_public_same_domain_email(self):
        contact = discovery.find_contact([COMPANY_PAGE], "acme.dev")
        assert contact.email == "ada@acme.dev"
        assert contact.name == "Ada"
        assert contact.contact_type == "public_email"
        assert contact.confidence == 88

    def test_finds_role_inbox(self):
        page = enricher.PageContent(
            url="https://acme.dev/about",
            text="Email sales@acme.dev to reach the team.",
        )
        contact = discovery.find_contact([page], "acme.dev")
        assert contact.email == "sales@acme.dev"
        assert contact.contact_type == "role_inbox"

    def test_useless_inbox_skipped(self):
        """Useless inboxes (support@, hello@, contact@) fall through to no contact."""
        page = enricher.PageContent(
            url="https://acme.dev/about",
            text="Email support@acme.dev or hello@acme.dev for help.",
        )
        contact = discovery.find_contact([page], "acme.dev")
        # Should fall through — these are useless for cold outreach
        assert contact.contact_type in ("not_found", "contact_page", "public_person")

    def test_useless_inbox_skipped_but_sales_kept(self):
        """When both useless and useful role inboxes exist, the useful one wins."""
        page = enricher.PageContent(
            url="https://acme.dev/contact",
            text="Contact support@acme.dev or sales@acme.dev.",
        )
        contact = discovery.find_contact([page], "acme.dev")
        assert contact.email == "sales@acme.dev"
        assert contact.contact_type == "role_inbox"

    def test_named_email_beats_role_inbox(self):
        page = enricher.PageContent(
            url="https://acme.dev/about",
            text="Email contact@acme.dev or ada.lovelace@acme.dev.",
        )
        contact = discovery.find_contact([page], "acme.dev")
        assert contact.email == "ada.lovelace@acme.dev"
        assert contact.name == "Ada Lovelace"
        assert contact.contact_type == "public_email"

    def test_ignores_other_domain_email(self):
        page = enricher.PageContent(url="https://acme.dev", text="Email hi@gmail.com")
        contact = discovery.find_contact([page], "acme.dev")
        assert contact.contact_type == "not_found"

    def test_guess_role_email_is_opt_in_low_confidence(self):
        page = enricher.PageContent(url="https://acme.dev/contact", text="No email here.")
        contact = discovery.find_contact([page], "acme.dev", guess_role_email=True)
        assert contact.email == "hello@acme.dev"
        assert contact.contact_type == "role_guess"
        assert contact.confidence == 30

    def test_finds_public_person_without_email(self):
        page = enricher.PageContent(
            url="https://acme.dev/about",
            text="Founder: Ada Lovelace builds developer tools.",
        )
        contact = discovery.find_contact([page], "acme.dev")
        assert contact.name == "Ada Lovelace"
        assert contact.role == "Founder"
        assert contact.contact_type == "public_person"

    def test_rejects_malformed_public_person_names(self):
        page = enricher.PageContent(
            url="https://acme.dev/about",
            text="CEO: Tytus Go. Head of Startups: The. Founder: Read.",
        )
        contact = discovery.find_contact([page], "acme.dev")
        assert contact.contact_type == "not_found"

    def test_role_relevant_inbox_scores_above_founder_person(self):
        inbox = discovery.Contact(
            email="partnerships@acme.dev",
            contact_type="role_inbox",
            confidence=84,
        )
        founder = discovery.Contact(
            name="Ada Lovelace",
            role="Founder",
            contact_type="public_person",
            confidence=55,
        )

        inbox_score, inbox_reasons = discovery.score_contact(inbox)
        founder_score, founder_reasons = discovery.score_contact(founder)

        assert inbox_score > founder_score
        assert "relevant_role_inbox" in inbox_reasons
        assert "exec_public_person" in founder_reasons


class TestSearchResolver:
    def test_parses_duckduckgo_html_result_urls(self):
        html = """
        <html><body>
          <a class="result__a" href="/l/?kh=-1&uddg=https%3A%2F%2Facme.dev%2Fteam">Team</a>
          <a class="result__a" href="https://acme.dev/contact">Contact</a>
          <a href="https://duckduckgo.com/y.js">Ad</a>
        </body></html>
        """

        urls = discovery.parse_search_result_urls(html)

        assert urls == ["https://acme.dev/team", "https://acme.dev/contact"]

    def test_search_result_filter_keeps_same_domain_useful_pages(self):
        assert discovery._search_result_allowed("https://acme.dev/team", "acme.dev")
        assert discovery._search_result_allowed("https://www.acme.dev/partnerships", "acme.dev")
        assert not discovery._search_result_allowed("https://linkedin.com/company/acme", "acme.dev")
        assert not discovery._search_result_allowed("https://acme.dev/login", "acme.dev")
        assert not discovery._search_result_allowed("https://acme.dev/logo.png", "acme.dev")

    @patch("opencold.discovery.web_search")
    def test_search_company_page_urls_uses_same_domain_results(self, mock_search):
        mock_search.return_value = [
            discovery.SearchResult(title="Team", url="https://acme.dev/team"),
            discovery.SearchResult(title="LinkedIn", url="https://linkedin.com/company/acme"),
            discovery.SearchResult(title="Login", url="https://acme.dev/login"),
        ]
        company = discovery.CandidateCompany("Acme", "https://acme.dev", "source", "reason")

        urls = discovery.search_company_page_urls(company, limit=1)

        assert urls == ["https://acme.dev/team"]

    @patch("opencold.discovery.enricher.fetch_page")
    @patch("opencold.discovery.search_company_page_urls")
    def test_search_company_pages_fetches_bounded_useful_results(self, mock_urls, mock_fetch_page):
        mock_urls.return_value = [
            "https://acme.dev/team",
            "https://acme.dev/contact",
            "https://acme.dev/partnerships",
        ]
        mock_fetch_page.side_effect = [
            enricher.PageContent(url="https://acme.dev/team", text="Team"),
            enricher.PageContent(url="https://acme.dev/contact", text="Contact"),
            enricher.PageContent(url="https://acme.dev/partnerships", text="Partners"),
        ]
        company = discovery.CandidateCompany("Acme", "https://acme.dev", "source", "reason")

        pages = discovery.search_company_pages(company, limit=2)

        assert [page.url for page in pages] == ["https://acme.dev/team", "https://acme.dev/contact"]


class TestDiscoverRows:
    @patch("opencold.discovery.search_company_pages", return_value=[])
    @patch("opencold.discovery.crawl_company_pages")
    @patch("opencold.discovery._fetch_source")
    def test_builds_prepare_compatible_rows(self, mock_fetch, mock_crawl, _mock_search):
        mock_fetch.return_value = SOURCE_HTML
        mock_crawl.return_value = [COMPANY_PAGE]

        rows = discovery.discover_rows(
            ["https://source.test/list"],
            icp="engineering release workflows",
            limit=5,
        )

        assert rows
        row = rows[0]
        assert {"email", "first_name", "last_name", "company", "website"} <= set(row)
        assert "lead_score" in row
        assert "lead_score_reasons" in row
        assert "contact_score" in row
        assert "contact_score_reasons" in row
        assert row["email"] == "ada@acme.dev"
        assert row["contact_type"] == "public_email"
        assert int(row["icp_score"]) > 50
        assert "engineering" in row["matched_terms"]

    @patch("opencold.discovery.search_linkedin_contacts", return_value=[])
    @patch("opencold.discovery.search_company_pages", return_value=[])
    @patch("opencold.discovery.crawl_company_pages", return_value=[])
    @patch("opencold.discovery._fetch_source", return_value=SOURCE_HTML)
    def test_require_contact_filters_contactless_rows(self, _mock_fetch, _mock_crawl, _mock_search, _mock_linkedin):
        rows = discovery.discover_rows(
            ["https://source.test/list"],
            require_contact=True,
        )
        assert rows == []

    @patch("opencold.discovery.search_linkedin_contacts", return_value=[])
    @patch("opencold.discovery.search_company_pages")
    @patch("opencold.discovery.crawl_company_pages")
    @patch("opencold.discovery._fetch_source")
    def test_search_pages_improve_contact_discovery(self, mock_fetch, mock_crawl, mock_search, _mock_linkedin):
        mock_fetch.return_value = SOURCE_HTML
        mock_crawl.return_value = [
            enricher.PageContent(
                url="https://acme.dev/about",
                text="Founder: Ada Lovelace builds developer tools.",
            )
        ]
        mock_search.return_value = [
            enricher.PageContent(
                url="https://acme.dev/partnerships",
                text="For partner programs email partnerships@acme.dev.",
            )
        ]

        rows = discovery.discover_rows(["https://source.test/list"], limit=1)

        assert rows[0]["email"] == "partnerships@acme.dev"
        assert rows[0]["contact_type"] == "role_inbox"
        assert int(rows[0]["contact_score"]) > 70

    @patch("opencold.discovery.enricher.fetch_page")
    def test_crawl_company_pages_checks_contact_page(self, mock_fetch_page):
        def fake_fetch(url):
            if url.endswith("/contact"):
                return enricher.PageContent(url=url, text="Reach us at hello@acme.dev")
            return enricher.PageContent(url=url, text="", status="fetch_failed")

        mock_fetch_page.side_effect = fake_fetch
        pages = discovery.crawl_company_pages("https://acme.dev", max_pages=4)

        assert len(pages) == 1
        assert pages[0].url == "https://acme.dev/contact"

    @patch("opencold.discovery._fetch_source")
    def test_discover_company_pool_uses_multiple_sources(self, mock_fetch):
        def fake_fetch(source):
            if source.endswith("one"):
                return '<a href="https://one.dev">One</a><a href="https://two.dev">Two</a>'
            return '<a href="https://three.dev">Three</a>'

        mock_fetch.side_effect = fake_fetch
        companies = discovery.discover_company_pool(
            ["https://source.test/one", "https://source.test/two"],
            limit=10,
            source_limit=1,
            workers=2,
        )
        websites = {c.website for c in companies}
        assert websites == {"https://one.dev", "https://three.dev"}

    @patch("opencold.discovery._fetch_source")
    def test_discover_from_source_follows_internal_detail_pages(self, mock_fetch):
        def fake_fetch(source):
            if source == "https://directory.test":
                return '<a href="/tool/acme">Acme</a>'
            if source == "https://directory.test/tool/acme":
                return '<a href="https://acme.dev">Visit website</a>'
            return ""

        mock_fetch.side_effect = fake_fetch
        companies = discovery.discover_from_source("https://directory.test", source_limit=5)
        assert len(companies) == 1
        assert companies[0].website == "https://acme.dev"

    def test_lead_score_penalizes_noisy_products(self):
        good = {
            "company": "Acme DevTools",
            "discovery_reason": "Developer observability platform",
            "company_summary": "Acme provides observability APIs for engineering teams.",
            "personalization_facts": "Acme helps developers monitor production workflows.",
            "icp_score": "74",
            "matched_terms": "observability",
            "personalization_score": "85",
            "contact_type": "public_person",
            "website_status": "ok",
        }
        noisy = {
            "company": "AI Fruit Video Generator",
            "discovery_reason": "Create viral TikTok ASMR fruit videos",
            "company_summary": "AI Fruit creates fruit-eating-fruit ASMR videos for TikTok and Instagram.",
            "personalization_facts": "Generate fruit videos and image generator clips.",
            "icp_score": "74",
            "matched_terms": "ai",
            "personalization_score": "85",
            "contact_type": "not_found",
            "website_status": "ok",
        }

        good_score, good_reasons = discovery.score_lead(good)
        noisy_score, noisy_reasons = discovery.score_lead(noisy)

        assert good_score > noisy_score
        assert "b2b_signal" in good_reasons
        assert "noisy_product" in noisy_reasons

    def test_rows_sort_by_lead_score(self):
        rows = [
            {
                "lead_score": "20",
                "contact_score": "100",
                "icp_score": "100",
                "personalization_score": "100",
            },
            {
                "lead_score": "90",
                "contact_score": "10",
                "icp_score": "10",
                "personalization_score": "10",
            },
        ]
        rows.sort(
            key=lambda r: (
                int(r.get("lead_score", "0")),
                int(r.get("contact_score", "0")),
                int(r.get("icp_score", "0")),
                int(r.get("personalization_score", "0")),
            ),
            reverse=True,
        )
        assert rows[0]["lead_score"] == "90"
