"""Tests for CLI helpers."""

from unittest.mock import patch

from opencold.cli import _clamp_workers, _enrich_rows, _validate_csv, do_run


class TestValidateCsv:
    def test_valid_rows_with_website(self):
        rows = [
            {
                "email": "a@test.com",
                "first_name": "A",
                "last_name": "B",
                "company": "C",
                "website": "https://c.com",
            },
        ]
        result = _validate_csv(rows)
        assert result == rows

    def test_missing_email_returns_none(self):
        rows = [
            {
                "email": "",
                "first_name": "A",
                "last_name": "B",
                "company": "C",
                "website": "https://c.com",
            },
        ]
        result = _validate_csv(rows)
        assert result is None

    def test_some_missing_email_returns_none(self):
        rows = [
            {
                "email": "a@test.com",
                "first_name": "A",
                "last_name": "B",
                "company": "C",
                "website": "https://c.com",
            },
            {
                "email": "",
                "first_name": "D",
                "last_name": "E",
                "company": "F",
                "website": "https://f.com",
            },
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
            {
                "email": "a@test.com",
                "first_name": "A",
                "last_name": "B",
                "company": "C",
                "website": "https://c.com",
            },
            {
                "email": "d@test.com",
                "first_name": "D",
                "last_name": "E",
                "company": "F",
                "website": "",
            },
        ]
        result = _validate_csv(rows)
        assert len(result) == 1
        assert result[0]["email"] == "a@test.com"

    @patch("opencold.cli._confirm", return_value=False)
    def test_missing_websites_cancel(self, mock_confirm):
        rows = [
            {
                "email": "a@test.com",
                "first_name": "A",
                "last_name": "B",
                "company": "C",
                "website": "https://c.com",
            },
            {
                "email": "d@test.com",
                "first_name": "D",
                "last_name": "E",
                "company": "F",
                "website": "",
            },
        ]
        result = _validate_csv(rows)
        assert result is None

    def test_all_have_websites_no_warning(self):
        rows = [
            {
                "email": "a@test.com",
                "first_name": "A",
                "last_name": "B",
                "company": "C",
                "website": "https://c.com",
            },
            {
                "email": "d@test.com",
                "first_name": "D",
                "last_name": "E",
                "company": "F",
                "website": "https://f.com",
            },
        ]
        result = _validate_csv(rows)
        assert len(result) == 2

    @patch("opencold.cli._confirm", return_value=True)
    def test_all_missing_websites_returns_none(self, mock_confirm):
        """If all rows lack website and user proceeds, filtering leaves nothing."""
        rows = [
            {
                "email": "a@test.com",
                "first_name": "A",
                "last_name": "B",
                "company": "C",
                "website": "",
            },
        ]
        result = _validate_csv(rows)
        assert result is None


class TestWorkers:
    def test_clamps_workers_to_max_eight(self):
        assert _clamp_workers(50) == 8

    def test_clamps_workers_to_min_one(self):
        assert _clamp_workers(0) == 1


class TestDraftRequiresEnriched:
    @patch("opencold.cli._validate_csv")
    @patch("opencold.cli._read_csv")
    @patch("opencold.cli._ensure_config")
    def test_draft_mode_rejects_raw_csv(self, mock_config, mock_read, mock_validate):
        rows = [
            {
                "email": "a@test.com",
                "first_name": "A",
                "last_name": "B",
                "company": "C",
                "website": "https://c.com",
            },
        ]
        mock_config.return_value = {}
        mock_read.return_value = rows
        mock_validate.return_value = rows

        with patch("opencold.cli.typer.echo") as mock_echo:
            do_run("leads.csv", require_enriched=True)

        output = "\n".join(str(call.args[0]) for call in mock_echo.call_args_list if call.args)
        assert "draft expects a prepared CSV" in output


class TestEnrichRows:
    @patch(
        "opencold.cli.verifier.verify_email",
        return_value={"email": "a@test.com", "valid": True, "reason": "ok"},
    )
    @patch("opencold.cli.enricher.enrich_website")
    def test_enriches_each_unique_website_once(self, mock_enrich_website, _mock_verify):
        mock_enrich_website.return_value = {
            "website_status": "ok",
            "company_summary": "Acme helps teams ship.",
            "personalization_facts": "Acme helps teams ship.",
            "source_urls": "https://acme.com",
            "personalization_score": "80",
            "quality_warnings": "",
            "enrichment_json": "{}",
        }
        rows = [
            {
                "email": "a@test.com",
                "first_name": "A",
                "last_name": "B",
                "company": "Acme",
                "website": "acme.com",
            },
            {
                "email": "b@test.com",
                "first_name": "B",
                "last_name": "C",
                "company": "Acme",
                "website": "https://acme.com",
            },
        ]

        with patch("opencold.cli.typer.echo"):
            enriched = _enrich_rows(rows, workers=2)

        assert len(enriched) == 2
        assert mock_enrich_website.call_count == 1


class TestDraftNeverSends:
    """REPL `draft` shares run's parser, so `--send` parses; it must never send."""

    def test_repl_draft_send_does_not_send(self, seeded_config, tmp_path):
        from types import SimpleNamespace

        csv_path = tmp_path / "enriched.csv"
        csv_path.write_text(
            "email,name,company,personalization_facts\na@acme.test,Ada,Acme,Builds things\n",
            encoding="utf-8",
        )
        out = tmp_path / "drafts.csv"
        draft_row = {
            "email": "a@acme.test",
            "name": "Ada",
            "company": "Acme",
            "personalization_facts": "Builds things",
            "generated_subject": "Hi",
            "generated_email": "Body",
        }
        result = SimpleNamespace(rows=[draft_row], success_count=1, total_count=1)
        lines = iter([f"draft {csv_path} -o {out} --send --system-prompt sp", "exit"])
        session = SimpleNamespace(prompt=lambda *a, **k: next(lines))
        smtp = {"host": "smtp.test", "port": 587, "sender_email": "me@test.com"}

        with (
            patch("opencold.cli.PromptSession", return_value=session),
            patch("opencold.cli._resolve_provider", return_value={"type": "anthropic"}),
            patch("opencold.cli.pipeline.generate_drafts", return_value=result),
            patch("opencold.cli.config.get_smtp", return_value=smtp),
            patch("opencold.cli._confirm", return_value=True),
            patch("opencold.cli._ask", return_value="Subject"),
            patch("opencold.cli.sender.send_email") as send_email,
        ):
            from opencold.cli import _run_shell

            _run_shell()

        send_email.assert_not_called()
