"""Tests for email verifier module."""

from unittest.mock import patch, MagicMock

import dns.resolver
import dns.exception

from opencold.verifier import (
    _check_format,
    _check_mx,
    verify_email,
    verify_emails,
    clear_cache,
)


class TestCheckFormat:
    def test_valid_email(self):
        assert _check_format("alice@acme.com") is None

    def test_valid_email_with_plus(self):
        assert _check_format("alice+tag@acme.com") is None

    def test_valid_email_with_dots(self):
        assert _check_format("a.b.c@sub.domain.co.uk") is None

    def test_empty_string(self):
        assert _check_format("") == "empty"

    def test_whitespace_only(self):
        assert _check_format("   ") == "empty"

    def test_none_like_empty(self):
        # Passing empty after strip
        assert _check_format("") == "empty"

    def test_missing_at(self):
        assert _check_format("alice.acme.com") == "invalid format"

    def test_missing_domain(self):
        assert _check_format("alice@") == "invalid format"

    def test_missing_tld(self):
        assert _check_format("alice@acme") == "invalid format"

    def test_double_at(self):
        assert _check_format("alice@@acme.com") == "invalid format"

    def test_spaces_in_email(self):
        assert _check_format("alice @acme.com") == "invalid format"

    def test_strips_whitespace(self):
        assert _check_format("  alice@acme.com  ") is None


class TestCheckMx:
    def setup_method(self):
        clear_cache()

    @patch("opencold.verifier.dns.resolver.Resolver")
    def test_valid_mx(self, mock_resolver_cls):
        resolver = MagicMock()
        resolver.resolve.return_value = [MagicMock()]  # one MX record
        mock_resolver_cls.return_value = resolver
        assert _check_mx("acme.com") is True

    @patch("opencold.verifier.dns.resolver.Resolver")
    def test_no_mx_nxdomain(self, mock_resolver_cls):
        resolver = MagicMock()
        resolver.resolve.side_effect = dns.resolver.NXDOMAIN()
        mock_resolver_cls.return_value = resolver
        assert _check_mx("nonexistent.invalid") is False

    @patch("opencold.verifier.dns.resolver.Resolver")
    def test_no_mx_no_answer(self, mock_resolver_cls):
        resolver = MagicMock()
        resolver.resolve.side_effect = dns.resolver.NoAnswer()
        mock_resolver_cls.return_value = resolver
        assert _check_mx("noanswer.invalid") is False

    @patch("opencold.verifier.dns.resolver.Resolver")
    def test_timeout_returns_false(self, mock_resolver_cls):
        resolver = MagicMock()
        resolver.resolve.side_effect = dns.exception.Timeout()
        mock_resolver_cls.return_value = resolver
        assert _check_mx("timeout.invalid") is False

    @patch("opencold.verifier.dns.resolver.Resolver")
    def test_unexpected_error_assumes_valid(self, mock_resolver_cls):
        resolver = MagicMock()
        resolver.resolve.side_effect = OSError("network down")
        mock_resolver_cls.return_value = resolver
        assert _check_mx("oserror.invalid") is True

    @patch("opencold.verifier.dns.resolver.Resolver")
    def test_cache_prevents_duplicate_lookups(self, mock_resolver_cls):
        resolver = MagicMock()
        resolver.resolve.return_value = [MagicMock()]
        mock_resolver_cls.return_value = resolver

        _check_mx("cached.com")
        _check_mx("cached.com")
        # Resolver class instantiated only once (first call)
        assert mock_resolver_cls.call_count == 1


class TestVerifyEmail:
    def setup_method(self):
        clear_cache()

    def test_empty_email(self):
        result = verify_email("")
        assert result["valid"] is False
        assert result["reason"] == "empty"

    def test_bad_format(self):
        result = verify_email("not-an-email")
        assert result["valid"] is False
        assert result["reason"] == "invalid format"

    @patch("opencold.verifier._check_mx", return_value=True)
    def test_valid_email(self, _mock_mx):
        result = verify_email("alice@acme.com")
        assert result["valid"] is True
        assert result["reason"] == "ok"
        assert result["email"] == "alice@acme.com"

    @patch("opencold.verifier._check_mx", return_value=False)
    def test_no_mx(self, _mock_mx):
        result = verify_email("alice@badomain.invalid")
        assert result["valid"] is False
        assert "no MX records" in result["reason"]

    @patch("opencold.verifier._check_mx", return_value=True)
    def test_strips_whitespace(self, _mock_mx):
        result = verify_email("  alice@acme.com  ")
        assert result["valid"] is True
        assert result["email"] == "alice@acme.com"


class TestVerifyEmails:
    @patch("opencold.verifier._check_mx", return_value=True)
    def test_batch(self, _mock_mx):
        results = verify_emails(["a@x.com", "bad", "b@y.com"])
        assert len(results) == 3
        assert results[0]["valid"] is True
        assert results[1]["valid"] is False
        assert results[2]["valid"] is True


class TestClearCache:
    @patch("opencold.verifier.dns.resolver.Resolver")
    def test_clear_forces_relookup(self, mock_resolver_cls):
        resolver = MagicMock()
        resolver.resolve.return_value = [MagicMock()]
        mock_resolver_cls.return_value = resolver

        clear_cache()
        _check_mx("test.com")
        clear_cache()
        _check_mx("test.com")
        # After clear, resolver should be created again
        assert mock_resolver_cls.call_count == 2
