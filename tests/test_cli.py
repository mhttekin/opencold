"""Tests for CLI helpers."""

from unittest.mock import patch
from opencold.cli import _validate_csv


class TestValidateCsv:
    def test_valid_rows_with_website(self):
        rows = [
            {"email": "a@test.com", "first_name": "A", "last_name": "B", "company": "C", "website": "https://c.com"},
        ]
        result = _validate_csv(rows)
        assert result == rows

    def test_missing_email_returns_none(self):
        rows = [
            {"email": "", "first_name": "A", "last_name": "B", "company": "C", "website": "https://c.com"},
        ]
        result = _validate_csv(rows)
        assert result is None

    def test_some_missing_email_returns_none(self):
        rows = [
            {"email": "a@test.com", "first_name": "A", "last_name": "B", "company": "C", "website": "https://c.com"},
            {"email": "", "first_name": "D", "last_name": "E", "company": "F", "website": "https://f.com"},
        ]
        result = _validate_csv(rows)
        assert result is None

    @patch("opencold.cli._confirm", return_value=True)
    def test_no_website_column_proceed(self, mock_confirm):
        rows = [
            {"email": "a@test.com", "first_name": "A", "last_name": "B", "company": "C"},
        ]
        result = _validate_csv(rows)
        assert result == rows

    @patch("opencold.cli._confirm", return_value=False)
    def test_no_website_column_cancel(self, mock_confirm):
        rows = [
            {"email": "a@test.com", "first_name": "A", "last_name": "B", "company": "C"},
        ]
        result = _validate_csv(rows)
        assert result is None

    @patch("opencold.cli._confirm", return_value=True)
    def test_missing_websites_filters_rows(self, mock_confirm):
        rows = [
            {"email": "a@test.com", "first_name": "A", "last_name": "B", "company": "C", "website": "https://c.com"},
            {"email": "d@test.com", "first_name": "D", "last_name": "E", "company": "F", "website": ""},
        ]
        result = _validate_csv(rows)
        assert len(result) == 1
        assert result[0]["email"] == "a@test.com"

    @patch("opencold.cli._confirm", return_value=False)
    def test_missing_websites_cancel(self, mock_confirm):
        rows = [
            {"email": "a@test.com", "first_name": "A", "last_name": "B", "company": "C", "website": "https://c.com"},
            {"email": "d@test.com", "first_name": "D", "last_name": "E", "company": "F", "website": ""},
        ]
        result = _validate_csv(rows)
        assert result is None

    def test_all_have_websites_no_warning(self):
        rows = [
            {"email": "a@test.com", "first_name": "A", "last_name": "B", "company": "C", "website": "https://c.com"},
            {"email": "d@test.com", "first_name": "D", "last_name": "E", "company": "F", "website": "https://f.com"},
        ]
        result = _validate_csv(rows)
        assert len(result) == 2

    @patch("opencold.cli._confirm", return_value=True)
    def test_all_missing_websites_returns_none(self, mock_confirm):
        """If all rows lack website and user proceeds, filtering leaves nothing."""
        rows = [
            {"email": "a@test.com", "first_name": "A", "last_name": "B", "company": "C", "website": ""},
        ]
        result = _validate_csv(rows)
        assert result is None
