"""Tests for LinkedIn contact discovery via web search results."""

from unittest.mock import patch, MagicMock

from opencold.discovery import (
    _company_name_matches,
    _download_reacher,
    _generate_email_patterns,
    _guess_email_from_name,
    _is_name_company_coincidence,
    _parse_linkedin_title,
    _reacher_check,
    _reacher_target_triple,
    parse_linkedin_result_titles,
    search_linkedin_contacts,
    verify_current_employment,
    score_contact,
    web_search,
    _serper_search,
    _ddgs_search,
    _brave_search,
    _ddg_html_search,
    SearchResult,
    Contact,
    LINKEDIN_TITLE_RE,
)


# ---------------------------------------------------------------------------
# Test LINKEDIN_TITLE_RE
# ---------------------------------------------------------------------------


class TestLinkedInTitleRegex:
    def test_standard_format(self):
        text = "Jane Smith - Marketing Manager - Acme Corp | LinkedIn"
        m = LINKEDIN_TITLE_RE.match(text)
        assert m is not None
        assert m.group("name") == "Jane Smith"
        assert m.group("role").strip() == "Marketing Manager"
        assert m.group("company").strip() == "Acme Corp"

    def test_en_dash_separator(self):
        text = "John Doe \u2013 Head of Growth \u2013 FooBar Inc | LinkedIn"
        m = LINKEDIN_TITLE_RE.match(text)
        assert m is not None
        assert m.group("name") == "John Doe"
        assert "Growth" in m.group("role")

    def test_em_dash_separator(self):
        text = "Alice Brown \u2014 Developer Relations \u2014 Cool Startup | LinkedIn"
        m = LINKEDIN_TITLE_RE.match(text)
        assert m is not None
        assert m.group("name") == "Alice Brown"

    def test_three_part_name(self):
        text = "Mary Jane Watson - Sales Director - BigCo | LinkedIn"
        m = LINKEDIN_TITLE_RE.match(text)
        assert m is not None
        assert m.group("name") == "Mary Jane Watson"

    def test_no_match_on_company_only(self):
        text = "Acme Corp | LinkedIn"
        m = LINKEDIN_TITLE_RE.match(text)
        assert m is None

    def test_no_match_on_random_text(self):
        text = "Some random page title about things"
        m = LINKEDIN_TITLE_RE.match(text)
        assert m is None

    def test_role_with_comma(self):
        text = "Bob Wilson - Senior Marketing Manager, EMEA - TechCo | LinkedIn"
        m = LINKEDIN_TITLE_RE.match(text)
        assert m is not None
        assert m.group("name") == "Bob Wilson"
        assert "Marketing" in m.group("role")


# ---------------------------------------------------------------------------
# Test _parse_linkedin_title
# ---------------------------------------------------------------------------


class TestParseLinkedInTitle:
    def test_valid_title(self):
        result = _parse_linkedin_title("Jane Smith - Marketing Manager - Acme Corp | LinkedIn")
        assert result is not None
        name, role, company = result
        assert name == "Jane Smith"
        assert "Marketing" in role
        assert "Acme" in company

    def test_invalid_name(self):
        result = _parse_linkedin_title("About Us - Company Page - Acme | LinkedIn")
        assert result is None

    def test_no_match(self):
        result = _parse_linkedin_title("Random page title")
        assert result is None


# ---------------------------------------------------------------------------
# Test _company_name_matches
# ---------------------------------------------------------------------------


class TestCompanyNameMatches:
    def test_exact_match(self):
        assert _company_name_matches("Acme", "Acme") is True

    def test_case_insensitive(self):
        assert _company_name_matches("ACME", "acme") is True

    def test_suffix_stripped(self):
        assert _company_name_matches("Acme Inc.", "Acme") is True
        assert _company_name_matches("Acme", "Acme Corporation") is True

    def test_contains_match(self):
        assert _company_name_matches("Acme Labs", "Acme") is True
        assert _company_name_matches("Acme", "Acme Labs") is True

    def test_token_overlap(self):
        assert _company_name_matches("Acme Data Solutions", "Acme Data") is True

    def test_no_match(self):
        assert _company_name_matches("Totally Different", "Acme Corp") is False

    def test_empty_strings(self):
        assert _company_name_matches("", "Acme") is False
        assert _company_name_matches("Acme", "") is False

    def test_llc_suffix(self):
        assert _company_name_matches("FreshBooks LLC", "FreshBooks") is True

    def test_gmbh_suffix(self):
        assert _company_name_matches("Celonis GmbH", "Celonis") is True


# ---------------------------------------------------------------------------
# Test name-company coincidence detection
# ---------------------------------------------------------------------------


class TestNameCompanyCoincidence:
    def test_matt_crisp_at_crisp(self):
        """Matt Crisp's URL is /in/mattcrisp — his name, not the company Crisp."""
        assert _is_name_company_coincidence(
            "Matt Crisp", "Crisp", "https://www.linkedin.com/in/mattcrisp"
        ) is True

    def test_eric_crisp_at_crisp(self):
        assert _is_name_company_coincidence(
            "Eric Crisp", "Crisp", "https://www.linkedin.com/in/eric-crisp-258a1651"
        ) is True

    def test_jonathan_crisp_at_crisp(self):
        assert _is_name_company_coincidence(
            "Jonathan Crisp", "Crisp", "https://www.linkedin.com/in/jonathan-crisp-3a69205"
        ) is True

    def test_real_employee_not_flagged(self):
        """Abrar Sami at Dorik — name doesn't match company, not a coincidence."""
        assert _is_name_company_coincidence(
            "Abrar Sami", "Dorik", "https://www.linkedin.com/in/productmarketer-abrar-sami"
        ) is False

    def test_name_slug_with_role_prefix(self):
        """URL with role prefix (productmarketer-) — not a pure name slug."""
        assert _is_name_company_coincidence(
            "Cooper Lower", "Botpress", "https://www.linkedin.com/in/cooper-lower"
        ) is False

    def test_single_name_returns_false(self):
        assert _is_name_company_coincidence(
            "Crisp", "Crisp", "https://www.linkedin.com/in/crisp"
        ) is False

    def test_different_last_name(self):
        """Last name doesn't match company — not a coincidence."""
        assert _is_name_company_coincidence(
            "Jane Smith", "Acme", "https://www.linkedin.com/in/janesmith"
        ) is False

    def test_random_slug_with_name_match(self):
        """Slug is random (label23), but last name matches company — coincidence."""
        assert _is_name_company_coincidence(
            "Jonathan Raymond Crisp", "Crisp", "https://www.linkedin.com/in/label23"
        ) is True

    def test_slug_with_company_context_not_coincidence(self):
        """Slug contains company name in non-name context — likely a real employee."""
        assert _is_name_company_coincidence(
            "John Crisp", "Crisp", "https://www.linkedin.com/in/john-at-crisp"
        ) is False

    def test_first_name_matches_company(self):
        """Mixo Baloyi at company Mixo — first name is the company name."""
        assert _is_name_company_coincidence(
            "Mixo Oral Baloyi", "Mixo", "https://za.linkedin.com/in/mixo-oral-baloyi-8954a5122"
        ) is True


# ---------------------------------------------------------------------------
# Test parse_linkedin_result_titles (DDG HTML fallback path)
# ---------------------------------------------------------------------------


class TestParseLinkedInResultTitles:
    def _make_html(self, links):
        """Build minimal HTML with <a> tags."""
        parts = []
        for href, text in links:
            parts.append(f'<a href="{href}" class="result__a">{text}</a>')
        return "<html><body>" + "\n".join(parts) + "</body></html>"

    def test_extracts_valid_profile(self):
        html = self._make_html([
            ("https://www.linkedin.com/in/janesmith", "Jane Smith - Marketing Manager - Acme Corp | LinkedIn"),
        ])
        results = parse_linkedin_result_titles(html)
        assert len(results) == 1
        name, role, company, url = results[0]
        assert name == "Jane Smith"
        assert "Marketing" in role
        assert "Acme" in company
        assert "linkedin.com/in" in url

    def test_skips_non_linkedin_links(self):
        html = self._make_html([
            ("https://example.com/page", "Jane Smith - Marketing Manager - Acme Corp | LinkedIn"),
        ])
        results = parse_linkedin_result_titles(html)
        assert len(results) == 0

    def test_skips_bad_names(self):
        html = self._make_html([
            ("https://www.linkedin.com/in/aboutpage", "About Us - Company Page - Acme | LinkedIn"),
        ])
        results = parse_linkedin_result_titles(html)
        assert len(results) == 0

    def test_multiple_results(self):
        html = self._make_html([
            ("https://www.linkedin.com/in/jsmith", "Jane Smith - Sales Manager - BigCo | LinkedIn"),
            ("https://www.linkedin.com/in/bdoe", "Bob Doe - Growth Lead - BigCo | LinkedIn"),
        ])
        results = parse_linkedin_result_titles(html)
        assert len(results) == 2

    def test_deduplicates_same_name(self):
        html = self._make_html([
            ("https://www.linkedin.com/in/jsmith1", "Jane Smith - Sales - BigCo | LinkedIn"),
            ("https://www.linkedin.com/in/jsmith2", "Jane Smith - Marketing - BigCo | LinkedIn"),
        ])
        results = parse_linkedin_result_titles(html)
        assert len(results) == 1

    def test_ddg_redirect_url(self):
        """DuckDuckGo wraps URLs in //duckduckgo.com/l/?uddg=<encoded_url>."""
        from urllib.parse import quote
        target = "https://www.linkedin.com/in/janesmith"
        ddg_href = f"//duckduckgo.com/l/?uddg={quote(target, safe='')}"
        html = self._make_html([
            (ddg_href, "Jane Smith - Marketing Manager - Acme Corp | LinkedIn"),
        ])
        results = parse_linkedin_result_titles(html)
        assert len(results) == 1
        assert "linkedin.com/in" in results[0][3]


# ---------------------------------------------------------------------------
# Test _generate_email_patterns and _reacher_check
# ---------------------------------------------------------------------------


class TestReacherTargetTriple:
    @patch("opencold.discovery.platform.machine", return_value="arm64")
    @patch("opencold.discovery.platform.system", return_value="Darwin")
    def test_macos_arm64_uses_x86(self, _s, _m):
        assert _reacher_target_triple() == "x86_64-apple-darwin"

    @patch("opencold.discovery.platform.machine", return_value="x86_64")
    @patch("opencold.discovery.platform.system", return_value="Darwin")
    def test_macos_x86(self, _s, _m):
        assert _reacher_target_triple() == "x86_64-apple-darwin"

    @patch("opencold.discovery.platform.machine", return_value="x86_64")
    @patch("opencold.discovery.platform.system", return_value="Linux")
    def test_linux_x86(self, _s, _m):
        assert _reacher_target_triple() == "x86_64-unknown-linux-gnu"

    @patch("opencold.discovery.platform.machine", return_value="aarch64")
    @patch("opencold.discovery.platform.system", return_value="Linux")
    def test_linux_arm64(self, _s, _m):
        assert _reacher_target_triple() == "aarch64-unknown-linux-gnu"

    @patch("opencold.discovery.platform.machine", return_value="x86_64")
    @patch("opencold.discovery.platform.system", return_value="Windows")
    def test_windows_returns_none(self, _s, _m):
        assert _reacher_target_triple() is None


class TestDownloadReacher:
    @patch("opencold.discovery._reacher_target_triple", return_value=None)
    def test_unsupported_platform_returns_none(self, _mock):
        assert _download_reacher() is None


class TestGenerateEmailPatterns:
    def test_generates_expected_patterns(self):
        patterns = _generate_email_patterns("jane", "smith", "acme.com")
        assert "jane.smith@acme.com" in patterns
        assert "jane@acme.com" in patterns
        assert "janesmith@acme.com" in patterns
        assert "jsmith@acme.com" in patterns
        assert "janes@acme.com" in patterns
        assert "j.smith@acme.com" in patterns
        assert "smith.jane@acme.com" in patterns
        assert "jane_smith@acme.com" in patterns
        assert "jane-smith@acme.com" in patterns

    def test_first_pattern_is_first_dot_last(self):
        patterns = _generate_email_patterns("alice", "wonder", "corp.io")
        assert patterns[0] == "alice.wonder@corp.io"


class TestReacherCheck:
    @patch("opencold.discovery._find_reacher_binary", return_value=None)
    def test_returns_none_when_no_binary(self, _mock):
        result = _reacher_check("test@example.com")
        assert result is None

    @patch("opencold.discovery.subprocess.run")
    @patch("opencold.discovery._find_reacher_binary", return_value="/usr/local/bin/check-if-email-exists")
    def test_parses_json_output(self, _mock_bin, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"is_reachable": "safe", "smtp": {"is_deliverable": true}}',
        )
        result = _reacher_check("jane@acme.com")
        assert result == {"is_reachable": "safe", "smtp": {"is_deliverable": True}}

    @patch("opencold.discovery.subprocess.run")
    @patch("opencold.discovery._find_reacher_binary", return_value="/usr/local/bin/check-if-email-exists")
    def test_returns_none_on_timeout(self, _mock_bin, mock_run):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="check", timeout=30)
        result = _reacher_check("jane@acme.com")
        assert result is None

    @patch("opencold.discovery.subprocess.run")
    @patch("opencold.discovery._find_reacher_binary", return_value="/usr/local/bin/check-if-email-exists")
    def test_returns_none_on_bad_json(self, _mock_bin, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="not json")
        result = _reacher_check("jane@acme.com")
        assert result is None


# ---------------------------------------------------------------------------
# Test _guess_email_from_name
# ---------------------------------------------------------------------------


class TestGuessEmailFromName:
    @patch("opencold.discovery._find_reacher_binary", return_value=None)
    @patch("opencold.verifier._check_mx", return_value=True)
    def test_no_reacher_returns_none(self, _mock_mx, _mock_reacher):
        """Without reacher binary, don't guess — return None."""
        result = _guess_email_from_name("Jane Smith", "acme.com")
        assert result is None

    @patch("opencold.discovery._find_reacher_binary", return_value=None)
    @patch("opencold.verifier._check_mx", return_value=True)
    def test_three_part_name_no_reacher_returns_none(self, _mock_mx, _mock_reacher):
        result = _guess_email_from_name("Mary Jane Watson", "bigco.io")
        assert result is None

    @patch("opencold.discovery._find_reacher_binary", return_value=None)
    @patch("opencold.verifier._check_mx", return_value=False)
    def test_no_mx_returns_none(self, _mock_mx, _mock_reacher):
        result = _guess_email_from_name("Jane Smith", "invalid.nonexistent")
        assert result is None

    def test_single_name_returns_none(self):
        result = _guess_email_from_name("Jane", "acme.com")
        assert result is None

    def test_empty_name_returns_none(self):
        result = _guess_email_from_name("", "acme.com")
        assert result is None

    @patch("opencold.discovery._reacher_check")
    @patch("opencold.discovery._find_reacher_binary", return_value="/usr/local/bin/check-if-email-exists")
    @patch("opencold.verifier._check_mx", return_value=True)
    def test_reacher_finds_safe_email(self, _mock_mx, _mock_bin, mock_reacher):
        """When reacher says 'safe', return that pattern."""
        mock_reacher.side_effect = [
            {"is_reachable": "invalid", "smtp": {}},  # first.last@ invalid
            {"is_reachable": "safe", "smtp": {}},      # first@ safe
        ]
        result = _guess_email_from_name("Jane Smith", "acme.com")
        assert result == "jane@acme.com"

    @patch("opencold.discovery._reacher_check")
    @patch("opencold.discovery._find_reacher_binary", return_value="/usr/local/bin/check-if-email-exists")
    @patch("opencold.verifier._check_mx", return_value=True)
    def test_reacher_catch_all_returns_first_last(self, _mock_mx, _mock_bin, mock_reacher):
        """Catch-all domain returns first.last@ as best guess."""
        mock_reacher.return_value = {"is_reachable": "risky", "smtp": {"is_catch_all": True}}
        result = _guess_email_from_name("Jane Smith", "acme.com")
        assert result == "jane.smith@acme.com"

    @patch("opencold.discovery._reacher_check")
    @patch("opencold.discovery._find_reacher_binary", return_value="/usr/local/bin/check-if-email-exists")
    @patch("opencold.verifier._check_mx", return_value=True)
    def test_reacher_all_invalid_returns_none(self, _mock_mx, _mock_bin, mock_reacher):
        """When all patterns return invalid, person doesn't work there — return None."""
        mock_reacher.return_value = {"is_reachable": "invalid", "smtp": {}}
        result = _guess_email_from_name("Jane Smith", "acme.com")
        assert result is None

    @patch("opencold.discovery._reacher_check")
    @patch("opencold.discovery._find_reacher_binary", return_value="/usr/local/bin/check-if-email-exists")
    @patch("opencold.verifier._check_mx", return_value=True)
    def test_reacher_mix_unknown_returns_none(self, _mock_mx, _mock_bin, mock_reacher):
        """When patterns return unknown, don't guess — return None."""
        mock_reacher.return_value = {"is_reachable": "unknown", "smtp": {}}
        result = _guess_email_from_name("Jane Smith", "acme.com")
        assert result is None

    @patch("opencold.discovery._reacher_check")
    @patch("opencold.discovery._find_reacher_binary", return_value="/usr/local/bin/check-if-email-exists")
    @patch("opencold.verifier._check_mx", return_value=True)
    def test_reacher_risky_non_catchall_returned(self, _mock_mx, _mock_bin, mock_reacher):
        """Risky but not catch-all still gets returned."""
        mock_reacher.side_effect = [
            {"is_reachable": "invalid", "smtp": {}},
            {"is_reachable": "invalid", "smtp": {}},
            {"is_reachable": "risky", "smtp": {"is_catch_all": False}},  # janesmith@
        ]
        result = _guess_email_from_name("Jane Smith", "acme.com")
        assert result == "janesmith@acme.com"


# ---------------------------------------------------------------------------
# Test web_search and backends
# ---------------------------------------------------------------------------


class TestWebSearch:
    @patch("opencold.discovery._ddgs_search")
    def test_uses_ddgs_when_available(self, mock_ddgs):
        mock_ddgs.return_value = [SearchResult(title="Test", url="https://example.com")]
        results = web_search("test query")
        assert len(results) == 1
        assert results[0].title == "Test"
        mock_ddgs.assert_called_once()

    @patch("opencold.discovery._ddgs_search")
    @patch("opencold.discovery._brave_search")
    def test_falls_back_to_brave(self, mock_brave, mock_ddgs):
        mock_ddgs.return_value = []
        mock_brave.return_value = [SearchResult(title="Brave Result", url="https://example.com")]
        results = web_search("test query")
        assert len(results) == 1
        assert results[0].title == "Brave Result"

    @patch("opencold.discovery._ddgs_search")
    @patch("opencold.discovery._brave_search")
    @patch("opencold.discovery._serper_search")
    def test_falls_back_to_serper(self, mock_serper, mock_brave, mock_ddgs):
        mock_ddgs.return_value = []
        mock_brave.return_value = []
        mock_serper.return_value = [SearchResult(title="Serper Result", url="https://example.com")]
        results = web_search("test query")
        assert len(results) == 1
        assert results[0].title == "Serper Result"

    @patch("opencold.discovery._ddgs_search")
    @patch("opencold.discovery._brave_search")
    @patch("opencold.discovery._serper_search")
    @patch("opencold.discovery._ddg_html_search")
    def test_falls_back_to_ddg_html(self, mock_ddg_html, mock_serper, mock_brave, mock_ddgs):
        mock_ddgs.return_value = []
        mock_brave.return_value = []
        mock_serper.return_value = []
        mock_ddg_html.return_value = [SearchResult(title="DDG HTML Result", url="https://example.com")]
        results = web_search("test query")
        assert len(results) == 1
        assert results[0].title == "DDG HTML Result"

    @patch("opencold.discovery._get_serper_key", return_value="test-key")
    @patch("opencold.discovery.urllib.request.urlopen")
    def test_serper_search_parses_response(self, mock_urlopen, _mock_key):
        import json
        response_data = {
            "organic": [
                {"title": "Jane Smith - Marketing - Acme | LinkedIn", "link": "https://linkedin.com/in/js", "snippet": "..."},
                {"title": "Bob Doe - Sales - Acme | LinkedIn", "link": "https://linkedin.com/in/bd", "snippet": "..."},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        results = _serper_search("test query", num=10)
        assert len(results) == 2
        assert results[0].title == "Jane Smith - Marketing - Acme | LinkedIn"
        assert results[0].url == "https://linkedin.com/in/js"

    @patch("opencold.discovery._get_serper_key", return_value=None)
    def test_serper_no_key_returns_empty(self, _mock_key):
        assert _serper_search("test") == []

    @patch("ddgs.DDGS")
    def test_ddgs_search_parses_results(self, mock_ddgs_cls):
        mock_instance = MagicMock()
        mock_instance.text.return_value = [
            {"title": "Jane Smith - Marketing | LinkedIn", "href": "https://linkedin.com/in/js", "body": "..."},
        ]
        mock_instance.__enter__ = lambda s: s
        mock_instance.__exit__ = MagicMock(return_value=False)
        mock_ddgs_cls.return_value = mock_instance

        results = _ddgs_search("test query")
        assert len(results) == 1
        assert results[0].title == "Jane Smith - Marketing | LinkedIn"
        assert results[0].url == "https://linkedin.com/in/js"

    @patch("opencold.discovery.urllib.request.urlopen")
    def test_brave_search_parses_results(self, mock_urlopen):
        import gzip
        # Brave HTML with LinkedIn results - the <a> text concatenates URL display + title
        html = """<html><body>
        <a href="https://www.linkedin.com/in/jsmith/">LinkedInlinkedin.com› in › jsmithJane Smith - Marketing Manager - Acme Corp | LinkedIn</a>
        <a href="https://www.linkedin.com/in/bdoe/">LinkedInlinkedin.com› in › bdoeBob Doe - Sales Director - Acme | LinkedIn</a>
        </body></html>"""
        compressed = gzip.compress(html.encode())
        mock_resp = MagicMock()
        mock_resp.read.return_value = compressed
        mock_resp.headers = {"Content-Encoding": "gzip"}
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        results = _brave_search("test query")
        assert len(results) == 2
        assert "Jane Smith" in results[0].title
        assert results[0].url == "https://www.linkedin.com/in/jsmith/"

    @patch("opencold.discovery.urllib.request.urlopen")
    def test_brave_search_handles_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection failed")
        assert _brave_search("test") == []


# ---------------------------------------------------------------------------
# Test search_linkedin_contacts (mocked web_search)
# ---------------------------------------------------------------------------


@patch("opencold.discovery.verify_current_employment", return_value=(True, "company_confirmed"))
class TestSearchLinkedInContacts:
    @patch("opencold.discovery.web_search")
    @patch("opencold.discovery.time.sleep")
    def test_finds_contacts(self, _mock_sleep, mock_search, _mock_verify):
        mock_search.return_value = [
            SearchResult(
                title="Jane Smith - Marketing Manager - Acme Corp | LinkedIn",
                url="https://www.linkedin.com/in/janesmith",
            ),
            SearchResult(
                title="Bob Doe - Sales Director - Acme Corp | LinkedIn",
                url="https://www.linkedin.com/in/bobdoe",
            ),
        ]
        results = search_linkedin_contacts("Acme Corp", "acme.com", max_queries=1)
        assert len(results) >= 1
        assert results[0].name == "Jane Smith"
        assert results[0].contact_type == "linkedin_profile"

    @patch("opencold.discovery.web_search")
    @patch("opencold.discovery.time.sleep")
    def test_filters_wrong_company(self, _mock_sleep, mock_search, _mock_verify):
        mock_search.return_value = [
            SearchResult(
                title="Jane Smith - Marketing Manager - Totally Different Co | LinkedIn",
                url="https://www.linkedin.com/in/janesmith",
            ),
        ]
        results = search_linkedin_contacts("Acme Corp", "acme.com", max_queries=1)
        assert len(results) == 0

    @patch("opencold.discovery.web_search")
    @patch("opencold.discovery.time.sleep")
    def test_short_circuits_on_first_success(self, mock_sleep, mock_search, _mock_verify):
        mock_search.return_value = [
            SearchResult(
                title="Jane Smith - Marketing Manager - Acme | LinkedIn",
                url="https://www.linkedin.com/in/janesmith",
            ),
        ]
        search_linkedin_contacts("Acme", "acme.com", max_queries=3)
        # Should only call web_search once since first query succeeded
        assert mock_search.call_count == 1

    @patch("opencold.discovery.web_search")
    @patch("opencold.discovery.time.sleep")
    def test_empty_results(self, _mock_sleep, mock_search, _mock_verify):
        mock_search.return_value = []
        results = search_linkedin_contacts("Acme", "acme.com", max_queries=1)
        assert results == []

    @patch("opencold.discovery.web_search")
    @patch("opencold.discovery.time.sleep")
    def test_skips_non_linkedin_urls(self, _mock_sleep, mock_search, _mock_verify):
        mock_search.return_value = [
            SearchResult(
                title="Jane Smith - Marketing Manager - Acme | LinkedIn",
                url="https://www.example.com/jane",  # not linkedin
            ),
        ]
        results = search_linkedin_contacts("Acme", "acme.com", max_queries=1)
        assert results == []

    @patch("opencold.discovery.web_search")
    @patch("opencold.discovery.time.sleep")
    def test_sorts_by_role_relevance(self, _mock_sleep, mock_search, _mock_verify):
        mock_search.return_value = [
            SearchResult(
                title="Bob Wilson - Software Engineer - Acme | LinkedIn",
                url="https://www.linkedin.com/in/bwilson",
            ),
            SearchResult(
                title="Jane Smith - Marketing Manager - Acme | LinkedIn",
                url="https://www.linkedin.com/in/jsmith",
            ),
        ]
        results = search_linkedin_contacts("Acme", "acme.com", max_queries=1)
        assert len(results) == 2
        # Marketing role should come first (targeted role)
        assert "Marketing" in results[0].role


# ---------------------------------------------------------------------------
# Test score_contact with linkedin_profile type
# ---------------------------------------------------------------------------


class TestScoreContactLinkedIn:
    def test_linkedin_relevant_role(self):
        c = Contact(
            name="Jane Smith",
            role="Marketing Manager",
            contact_type="linkedin_profile",
            confidence=70,
        )
        score, reasons = score_contact(c)
        assert score > 60
        assert "linkedin_relevant_role" in reasons

    def test_linkedin_non_target_role(self):
        c = Contact(
            name="Jane Smith",
            role="Software Engineer",
            contact_type="linkedin_profile",
            confidence=50,
        )
        score, reasons = score_contact(c)
        assert "linkedin_profile" in reasons
        assert score >= 55

    def test_linkedin_scores_higher_than_public_person(self):
        linkedin = Contact(
            name="Jane Smith",
            role="Growth Lead",
            contact_type="linkedin_profile",
            confidence=70,
        )
        public = Contact(
            name="Jane Smith",
            role="Growth Lead",
            contact_type="public_person",
            confidence=55,
        )
        linkedin_score, _ = score_contact(linkedin)
        public_score, _ = score_contact(public)
        assert linkedin_score > public_score


# ---------------------------------------------------------------------------
# Test verify_current_employment
# ---------------------------------------------------------------------------


class TestVerifyCurrentEmployment:
    @patch("opencold.discovery._ddgs_search")
    def test_confirms_when_company_in_linkedin_title(self, mock_ddgs):
        mock_ddgs.return_value = [
            SearchResult(
                title="Jane Smith - Marketing Manager - Acme Corp | LinkedIn",
                url="https://linkedin.com/in/jsmith",
                snippet="Jane Smith is a Marketing Manager at Acme Corp.",
            ),
        ]
        is_current, reason = verify_current_employment("Jane Smith", "Acme Corp")
        assert is_current is True
        assert "confirmed_by" in reason

    @patch("opencold.discovery._ddgs_search")
    def test_no_results_gives_benefit_of_doubt(self, mock_ddgs):
        mock_ddgs.return_value = []
        is_current, reason = verify_current_employment("Cooper Lower", "Botpress")
        assert is_current is True
        assert reason == "no_results_benefit"

    @patch("opencold.discovery._ddgs_search")
    def test_detects_moved_to_new_company(self, mock_ddgs):
        mock_ddgs.return_value = [
            SearchResult(
                title="Cooper Lower - Brand Director | LinkedIn",
                url="https://linkedin.com/in/cooperlower",
                snippet="Cooper Lower now at HubSpot. Previously at Botpress.",
            ),
        ]
        is_current, reason = verify_current_employment("Cooper Lower", "Botpress")
        assert is_current is False
        assert "moved_to" in reason

    @patch("opencold.discovery._ddgs_search")
    def test_confirms_when_company_tokens_in_title(self, mock_ddgs):
        mock_ddgs.return_value = [
            SearchResult(
                title="Damla Yamanoglu - Hostinger | LinkedIn",
                url="https://linkedin.com/in/dy",
                snippet="Damla works on partnerships at Hostinger International.",
            ),
        ]
        is_current, reason = verify_current_employment("Damla Yamanoglu", "Hostinger")
        assert is_current is True

    @patch("opencold.discovery._ddgs_search")
    def test_short_company_name_gets_benefit_of_doubt(self, mock_ddgs):
        """When LinkedIn title doesn't mention short company name, benefit of doubt."""
        mock_ddgs.return_value = [
            SearchResult(
                title="Alex Rapp - Engineer | LinkedIn",
                url="https://linkedin.com/in/arapp",
                snippet="Alex works on infrastructure.",
            ),
        ]
        is_current, reason = verify_current_employment("Alex Rapp", "Zap")
        assert is_current is True
        assert reason == "short_company_name_benefit"

    @patch("opencold.discovery._ddgs_search")
    def test_search_failure_gives_benefit_of_doubt(self, mock_ddgs):
        mock_ddgs.side_effect = Exception("Network error")
        is_current, reason = verify_current_employment("Jane Smith", "Acme")
        assert is_current is True
        assert reason == "no_results_benefit"

    @patch("opencold.discovery._ddgs_search")
    def test_company_not_in_title_rejected(self, mock_ddgs):
        """If LinkedIn title shows different company, reject."""
        mock_ddgs.return_value = [
            SearchResult(
                title="Abrar Sami - Designer at Figma | LinkedIn",
                url="https://linkedin.com/in/abrarsami",
                snippet="Abrar is a product designer.",
            ),
        ]
        is_current, reason = verify_current_employment("Abrar Sami", "Dorik")
        assert is_current is False

    @patch("opencold.discovery._ddgs_search")
    def test_opentowork_signal_rejects(self, mock_ddgs):
        """People actively job-hunting are not at the target company."""
        mock_ddgs.return_value = [
            SearchResult(
                title="Cooper Lower - Product Marketing | LinkedIn",
                url="https://linkedin.com/in/cooperlower",
                snippet="#opentowork #productmarketing Looking for new opportunities.",
            ),
        ]
        is_current, reason = verify_current_employment("Cooper Lower", "Botpress")
        assert is_current is False
        assert reason == "not_currently_employed"

    @patch("opencold.discovery._ddgs_search")
    def test_joined_pattern_detects_move(self, mock_ddgs):
        mock_ddgs.return_value = [
            SearchResult(
                title="John Doe - Engineer | LinkedIn",
                url="https://linkedin.com/in/johndoe",
                snippet="John Doe joined Stripe in 2024 after leaving Acme.",
            ),
        ]
        is_current, reason = verify_current_employment("John Doe", "Acme")
        assert is_current is False
        assert "moved_to" in reason
        assert "Stripe" in reason

    @patch("opencold.discovery._ddgs_search")
    def test_same_company_in_moved_pattern_not_flagged(self, mock_ddgs):
        """If 'currently at X' matches the target company in snippet, confirm via snippet."""
        mock_ddgs.return_value = [
            SearchResult(
                title="Jane Smith | LinkedIn",
                url="https://linkedin.com/in/jsmith",
                snippet="Jane Smith currently at Acme working on partnerships.",
            ),
        ]
        is_current, reason = verify_current_employment("Jane Smith", "Acme")
        assert is_current is True

    @patch("opencold.discovery._ddgs_search")
    def test_snippet_confirms_when_title_unclear(self, mock_ddgs):
        """Company in snippet but not title still confirms."""
        mock_ddgs.return_value = [
            SearchResult(
                title="William Quillin | LinkedIn",
                url="https://linkedin.com/in/wquillin",
                snippet="William works at Manychat on growth initiatives.",
            ),
        ]
        is_current, reason = verify_current_employment("William Quillin", "Manychat")
        assert is_current is True
        assert "confirm" in reason

    @patch("opencold.discovery._ddgs_search")
    def test_site_query_contradicts_overrides_snippet(self, mock_ddgs):
        """site:linkedin.com/in showing different company rejects even if snippet has old company."""
        call_count = [0]
        def side_effect(query, num):
            call_count[0] += 1
            if "site:linkedin.com/in" in query:
                return [SearchResult(
                    title="Maryia Fokina – JobLeads | LinkedIn",
                    url="https://linkedin.com/in/maryia-fokina",
                    snippet="Digital PR & Content Marketing Manager",
                )]
            else:
                return [SearchResult(
                    title="Maryia Fokina, Author at Tidio",
                    url="https://tidio.com/author/maryia",
                    snippet="Maryia Fokina PR & Content Specialist at Tidio",
                )]
        mock_ddgs.side_effect = side_effect
        is_current, reason = verify_current_employment("Maryia Fokina", "Tidio")
        assert is_current is False
        assert "contradict" in reason or "JobLeads" in reason


# ---------------------------------------------------------------------------
# Test verification integration in search_linkedin_contacts
# ---------------------------------------------------------------------------


class TestVerificationIntegration:
    @patch("opencold.discovery.verify_current_employment")
    @patch("opencold.discovery.web_search")
    @patch("opencold.discovery.time.sleep")
    def test_verified_contacts_kept(self, _mock_sleep, mock_search, mock_verify):
        mock_search.return_value = [
            SearchResult(
                title="Jane Smith - Marketing Manager - Acme | LinkedIn",
                url="https://www.linkedin.com/in/jsmith",
            ),
        ]
        mock_verify.return_value = (True, "company_confirmed")
        results = search_linkedin_contacts("Acme", "acme.com", max_queries=1)
        assert len(results) == 1
        assert results[0].name == "Jane Smith"
        mock_verify.assert_called_once_with("Jane Smith", "Acme")

    @patch("opencold.discovery.verify_current_employment")
    @patch("opencold.discovery.web_search")
    @patch("opencold.discovery.time.sleep")
    def test_unverified_high_confidence_returned_reduced(self, _mock_sleep, mock_search, mock_verify):
        mock_search.return_value = [
            SearchResult(
                title="Jane Smith - Marketing Manager - Acme | LinkedIn",
                url="https://www.linkedin.com/in/jsmith",
            ),
        ]
        mock_verify.return_value = (False, "company_not_in_results")
        results = search_linkedin_contacts("Acme", "acme.com", max_queries=1)
        # High-confidence (marketing = 70) contact returned with reduced confidence
        assert len(results) == 1
        assert results[0].confidence < 70

    @patch("opencold.discovery.verify_current_employment")
    @patch("opencold.discovery.web_search")
    @patch("opencold.discovery.time.sleep")
    def test_unverified_low_confidence_dropped(self, _mock_sleep, mock_search, mock_verify):
        mock_search.return_value = [
            SearchResult(
                title="Bob Wilson - Software Engineer - Acme | LinkedIn",
                url="https://www.linkedin.com/in/bwilson",
            ),
        ]
        mock_verify.return_value = (False, "no_association_found")
        results = search_linkedin_contacts("Acme", "acme.com", max_queries=1)
        # Low-confidence (non-target role = 50 < 70) dropped entirely
        assert results == []
