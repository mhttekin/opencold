"""Tests for crawler module (no real HTTP calls)."""

from unittest.mock import patch, MagicMock
from opencold.crawler import crawl_website, _clean_text, _extract_meta, _extract_bs4


class TestCleanText:
    def test_removes_short_lines(self):
        text = "Hello world this is content\nOK\nAnother real line here"
        cleaned = _clean_text(text)
        assert "OK" not in cleaned
        assert "Hello world" in cleaned

    def test_removes_junk_patterns(self):
        text = "Skip to content\nSign up for free\nWe build great products for teams"
        cleaned = _clean_text(text)
        assert "Skip to" not in cleaned
        assert "Sign up" not in cleaned
        assert "great products" in cleaned

    def test_removes_timestamps(self):
        text = "karri · 2min ago\nThis is the real content of the page"
        cleaned = _clean_text(text)
        assert "2min ago" not in cleaned
        assert "real content" in cleaned

    def test_removes_duplicates(self):
        text = "We build products\nWe build products\nSomething else entirely"
        cleaned = _clean_text(text)
        assert cleaned.count("We build products") == 1

    def test_case_insensitive_dedup(self):
        text = "We Build Products\nwe build products\nUnique line for testing"
        cleaned = _clean_text(text)
        lines = cleaned.splitlines()
        lower_lines = [l.lower() for l in lines]
        assert lower_lines.count("we build products") == 1


class TestExtractMeta:
    def test_extracts_title(self):
        html = "<html><head><title>Acme Corp — Build Better</title></head><body></body></html>"
        result = _extract_meta(html)
        assert "Acme Corp" in result

    def test_extracts_meta_description(self):
        html = '<html><head><meta name="description" content="We make rockets"></head><body></body></html>'
        result = _extract_meta(html)
        assert "We make rockets" in result

    def test_extracts_og_description(self):
        html = '<html><head><meta property="og:description" content="Rocket company"></head><body></body></html>'
        result = _extract_meta(html)
        assert "Rocket company" in result

    def test_returns_none_for_empty(self):
        html = "<html><head></head><body></body></html>"
        result = _extract_meta(html)
        assert result is None


class TestExtractBs4:
    def test_strips_scripts_and_styles(self):
        html = """
        <html><body>
            <script>var x = 1;</script>
            <style>.a{color:red}</style>
            <p>Real content here</p>
        </body></html>
        """
        result = _extract_bs4(html)
        assert "var x" not in result
        assert "color:red" not in result
        assert "Real content here" in result

    def test_prefers_main_tag(self):
        html = """
        <html><body>
            <div>Sidebar junk that should be ignored</div>
            <main><p>Main content about our company</p></main>
        </body></html>
        """
        result = _extract_bs4(html)
        assert "Main content" in result


class TestCrawlWebsite:
    def test_empty_url_returns_none(self):
        assert crawl_website("") is None
        assert crawl_website(None) is None

    def test_prepends_https(self):
        with patch("opencold.crawler.trafilatura") as mock_traf:
            mock_traf.fetch_url.return_value = None
            with patch("opencold.crawler._fetch_html", return_value=None):
                crawl_website("example.com")
            # First call should be the main URL with https prepended
            first_call = mock_traf.fetch_url.call_args_list[0]
            assert first_call.args[0] == "https://example.com"

    def test_returns_cleaned_text(self):
        fake_html = """
        <html><head><title>TestCo</title>
        <meta name="description" content="We build widgets">
        </head><body><main>
        <p>TestCo is the leading widget platform for modern teams.</p>
        <p>Our widgets integrate with everything you already use.</p>
        </main></body></html>
        """
        with patch("opencold.crawler.trafilatura") as mock_traf:
            mock_traf.fetch_url.return_value = fake_html
            mock_traf.extract.return_value = "TestCo is the leading widget platform for modern teams."

            result = crawl_website("https://testco.com")
            assert result is not None
            assert "TestCo" in result
            assert "widget" in result

    def test_falls_back_to_bs4(self):
        fake_html = "<html><body><main><p>Fallback content from BeautifulSoup</p></main></body></html>"
        with patch("opencold.crawler.trafilatura") as mock_traf:
            mock_traf.fetch_url.return_value = fake_html
            mock_traf.extract.return_value = None  # trafilatura fails

            result = crawl_website("https://example.com")
            assert result is not None
            assert "Fallback content" in result

    def test_max_chars_truncation(self):
        with patch("opencold.crawler.trafilatura") as mock_traf:
            mock_traf.fetch_url.return_value = "<html><body>x</body></html>"
            mock_traf.extract.return_value = "A" * 5000

            result = crawl_website("https://example.com", max_chars=100)
            assert len(result) <= 100

    def test_handles_fetch_failure(self):
        with patch("opencold.crawler.trafilatura") as mock_traf:
            mock_traf.fetch_url.return_value = None
            with patch("opencold.crawler._fetch_html", return_value=None):
                result = crawl_website("https://down.example.com")
                assert result is None
