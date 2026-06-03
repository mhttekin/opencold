"""Tests for deterministic lead enrichment."""

from unittest.mock import patch

from opencold import enricher


HTML = """
<html>
  <head>
    <title>Acme AI - Support automation for finance teams</title>
    <meta name="description" content="Acme AI helps finance teams automate invoice review and vendor support.">
    <script type="application/ld+json">
      {"@type": "Organization", "name": "Acme AI", "description": "Acme AI provides AI agents for accounts payable teams."}
    </script>
  </head>
  <body>
    <main>
      <h1>Automate vendor support without adding headcount</h1>
      <p>Acme AI integrates with ERP systems and helps teams resolve invoice questions faster.</p>
      <p>Cookie settings and newsletter signup should not become facts.</p>
    </main>
  </body>
</html>
"""


class TestNormalizeUrl:
    def test_adds_https(self):
        assert enricher.normalize_url("example.com") == "https://example.com"

    def test_empty_url(self):
        assert enricher.normalize_url("") == ""


class TestExtractFacts:
    def test_extracts_structured_page_facts(self):
        page = enricher._extract_structured_html(HTML, "https://acme.test")
        facts = enricher.extract_facts([page])
        texts = [f.text for f in facts]

        assert any("helps finance teams" in text for text in texts)
        assert any("ERP systems" in text for text in texts)
        assert all("Cookie settings" not in text for text in texts)
        assert facts[0].confidence >= facts[-1].confidence

    def test_personalization_score_zero_without_facts(self):
        assert enricher.personalization_score([]) == 0

    def test_source_urls_are_deduplicated(self):
        facts = [
            enricher.Fact("One useful company fact", "https://a.test", "meta", 0.8),
            enricher.Fact("Another useful company fact", "https://a.test", "body", 0.6),
        ]
        assert enricher.source_urls(facts) == "https://a.test"

    def test_filters_pricing_cta_copy(self):
        page = enricher.PageContent(
            url="https://linear.app/pricing",
            text=(
                "Upgrade to enable unlimited issues, enhanced security controls, and additional features.\n"
                "Purpose-built for planning and building products with AI agents."
            ),
        )
        facts = enricher.extract_facts([page])
        texts = [f.text for f in facts]
        assert not any("Upgrade to enable" in text for text in texts)
        assert any("Purpose-built" in text for text in texts)

    def test_collapses_repeated_phrases(self):
        text = enricher._clean_sentence(
            "The product development system for teams and agents "
            "The product development system for teams and agents"
        )
        assert text == "The product development system for teams and agents"


class TestEnrichRow:
    @patch("opencold.enricher.verifier.verify_email")
    @patch("opencold.enricher.crawl_site")
    def test_enrich_row_outputs_csv_fields(self, mock_crawl, mock_verify):
        mock_verify.return_value = {"email": "a@acme.test", "valid": True, "reason": "ok"}
        mock_crawl.return_value = [enricher._extract_structured_html(HTML, "https://acme.test")]

        row = {
            "email": "a@acme.test",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "company": "Acme",
            "website": "https://acme.test",
        }
        result = enricher.enrich_row(row)

        assert result["verification_status"] == "valid"
        assert result["website_status"] == "ok"
        assert "helps finance teams" in result["personalization_facts"]
        assert result["source_urls"] == "https://acme.test"
        assert int(result["personalization_score"]) > 0
        assert result["enrichment_json"].startswith("{")

    @patch("opencold.enricher.verifier.verify_email")
    def test_enrich_row_without_website_warns(self, mock_verify):
        mock_verify.return_value = {"email": "a@acme.test", "valid": True, "reason": "ok"}
        result = enricher.enrich_row({"email": "a@acme.test", "website": ""})
        assert result["website_status"] == "missing"
        assert "no_grounded_facts" in result["quality_warnings"]
