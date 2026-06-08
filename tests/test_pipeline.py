"""Tests for the headless draft-generation pipeline (opencold.pipeline)."""

from unittest.mock import patch

from opencold import pipeline


def _fake_generation(provider_config, system_prompt, user_prompt, model, max_tokens):
    return {"subject": "Quick idea", "body": "First para.\n\nSecond para.\n\nThird para."}


class TestGenerateDrafts:
    def test_returns_result_rows_with_generated_fields(self):
        leads = [
            {"name": "Ada Lovelace", "company": "Analytical", "email": "ada@analytical.com"},
            {"name": "Alan Turing", "company": "Bombe", "email": "alan@bombe.com"},
        ]
        with patch("opencold.generator.generate_with_retry", side_effect=_fake_generation):
            result = pipeline.generate_drafts(
                leads,
                {"title": "T", "description": "d", "pitch": "p"},
                {"name": "Me", "email": "me@x.com"},
                {"company": "Acme", "role": "Founder", "bio": "b", "pitch": "p"},
                {"type": "anthropic", "api_key": "sk-test", "model": "claude-sonnet-4-6"},
                do_resolve_websites=False,
                do_enrich=False,
                do_verify=False,
            )

        assert result.total_count == 2
        assert result.success_count == 2
        assert len(result.rows) == 2
        for row in result.rows:
            assert row["generated_subject"] == "Quick idea"
            assert "First para." in row["generated_email"]
            assert "quality_warnings" in row
        # Input columns are preserved.
        assert result.rows[0]["name"] == "Ada Lovelace"

    def test_does_not_mutate_caller_input(self):
        leads = [{"name": "Ada", "company": "Analytical", "email": "ada@analytical.com"}]
        with patch("opencold.generator.generate_with_retry", side_effect=_fake_generation):
            pipeline.generate_drafts(
                leads, {}, {"name": "Me"}, {}, {"api_key": "k", "model": "m"},
                do_resolve_websites=False, do_enrich=False, do_verify=False,
            )
        assert "generated_email" not in leads[0]

    def test_provider_dict_maps_to_generator_config(self):
        captured = {}

        def _capture(provider_config, *args, **kwargs):
            captured.update(provider_config)
            return {"subject": "s", "body": "a\n\nb\n\nc"}

        leads = [{"name": "Ada", "company": "A", "email": "a@a.com"}]
        with patch("opencold.generator.generate_with_retry", side_effect=_capture):
            pipeline.generate_drafts(
                leads, {}, {}, {},
                {"type": "proxy", "api_key": "tok", "model": "custom-1", "base_url": "https://x"},
                do_resolve_websites=False, do_enrich=False, do_verify=False,
            )
        assert captured["type"] == "proxy"
        assert captured["api_key"] == "tok"
        assert captured["default_model"] == "custom-1"
        assert captured["base_url"] == "https://x"

    def test_drop_invalid_drops_unverifiable_emails(self):
        leads = [
            {"name": "Good", "company": "A", "email": "good@a.com"},
            {"name": "Bad", "company": "B", "email": "not-an-email"},
        ]
        good = {"email": "good@a.com", "valid": True, "reason": "ok"}
        bad = {"email": "not-an-email", "valid": False, "reason": "invalid format"}

        def _verify(email):
            return good if email == "good@a.com" else bad

        with patch("opencold.verifier.verify_email", side_effect=_verify), \
             patch("opencold.generator.generate_with_retry", side_effect=_fake_generation):
            result = pipeline.generate_drafts(
                leads, {}, {}, {}, {"api_key": "k", "model": "m"},
                do_resolve_websites=False, do_enrich=False, do_verify=True, drop_invalid=True,
            )

        assert result.total_count == 1
        assert len(result.dropped) == 1
        assert result.dropped[0]["reason"] == "invalid format"

    def test_generation_failure_is_captured_per_row(self):
        leads = [{"name": "Ada", "company": "A", "email": "a@a.com"}]
        with patch("opencold.generator.generate_with_retry", side_effect=RuntimeError("boom")):
            result = pipeline.generate_drafts(
                leads, {}, {}, {}, {"api_key": "k", "model": "m"},
                do_resolve_websites=False, do_enrich=False, do_verify=False,
            )
        assert result.success_count == 0
        assert result.rows[0]["generated_email"].startswith("ERROR:")
        assert "generation_failed" in result.rows[0]["quality_warnings"]

    def test_empty_leads_returns_empty_result(self):
        result = pipeline.generate_drafts(
            [], {}, {}, {}, {"api_key": "k", "model": "m"},
        )
        assert result.rows == []
        assert result.total_count == 0
