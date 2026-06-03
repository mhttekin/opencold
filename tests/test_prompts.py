"""Tests for prompts module."""

from opencold.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    build_template_prompt,
    _is_usable_text,
    _sanitize_website_text,
    _pick_structure,
    _STRUCTURES,
)


class TestSystemPrompt:
    def test_prompt_exists(self):
        assert len(SYSTEM_PROMPT) > 100

    def test_prompt_contains_word_limit(self):
        assert "80 words" in SYSTEM_PROMPT

    def test_prompt_bans_genuinely(self):
        lower = SYSTEM_PROMPT.lower()
        assert "genuinely" in lower

    def test_prompt_forbids_meta_commentary(self):
        lower = SYSTEM_PROMPT.lower()
        assert "fourth wall" in lower or "data quality" in lower

    def test_prompt_requires_variance(self):
        assert "variance" in SYSTEM_PROMPT.lower() or "different" in SYSTEM_PROMPT.lower()

    def test_prompt_requires_always_output(self):
        lower = SYSTEM_PROMPT.lower()
        assert "always" in lower
        assert "never refuse" in lower

    def test_prompt_handles_bad_input(self):
        lower = SYSTEM_PROMPT.lower()
        assert "nonsensical" in lower or "gibberish" in lower


class TestSanitizeWebsiteText:
    def test_usable_text_passes(self):
        text = "Acme Corp builds rockets for Mars colonization. Founded in 2020."
        assert _is_usable_text(text) is True

    def test_short_text_fails(self):
        assert _is_usable_text("hi") is False

    def test_empty_text_fails(self):
        assert _is_usable_text("") is False
        assert _is_usable_text(None) is False

    def test_sanitize_returns_none_for_bad(self):
        assert _sanitize_website_text("") is None
        assert _sanitize_website_text("abc") is None

    def test_sanitize_returns_text_for_good(self):
        good = "This is a perfectly normal company description with enough words."
        result = _sanitize_website_text(good)
        assert result is not None
        assert "normal company" in result


class TestBuildUserPrompt:
    ROW = {
        "first_name": "Alice",
        "last_name": "Smith",
        "company": "Acme",
        "email": "alice@acme.com",
    }
    IDENTITY = {"name": "Bob Builder", "email": "bob@test.com"}
    PROFILE = {"company": "BuildCo", "role": "Founder", "bio": "I build tools", "pitch": "Automate everything"}

    def test_contains_recipient(self):
        campaign = {"title": "Test", "description": "We do X", "pitch": "Try X"}
        prompt = build_user_prompt(self.ROW, self.IDENTITY, self.PROFILE, campaign)
        assert "Alice Smith" in prompt
        assert "Acme" in prompt

    def test_contains_sender(self):
        campaign = {"title": "Test", "description": "We do X", "pitch": "Try X"}
        prompt = build_user_prompt(self.ROW, self.IDENTITY, self.PROFILE, campaign)
        assert "Bob Builder" in prompt
        assert "BuildCo" in prompt
        assert "Founder" in prompt

    def test_uses_campaign_context(self):
        campaign = {"title": "SaaS", "description": "We do AI", "pitch": "Try our AI"}
        prompt = build_user_prompt(self.ROW, self.IDENTITY, self.PROFILE, campaign)
        assert "We do AI" in prompt
        assert "Try our AI" in prompt

    def test_falls_back_to_profile(self):
        campaign = {"title": "Minimal", "description": "", "pitch": ""}
        prompt = build_user_prompt(self.ROW, self.IDENTITY, self.PROFILE, campaign)
        assert "I build tools" in prompt
        assert "Automate everything" in prompt

    def test_website_text_included_when_readable(self):
        campaign = {"title": "Test", "description": "We do X", "pitch": "Try X"}
        prompt = build_user_prompt(
            self.ROW, self.IDENTITY, self.PROFILE, campaign,
            website_text="Acme builds rockets for Mars colonization and space exploration.",
        )
        assert "Acme builds rockets" in prompt
        assert "website content" in prompt.lower()

    def test_personalization_facts_take_priority(self):
        campaign = {"title": "Test", "description": "We do X", "pitch": "Try X"}
        prompt = build_user_prompt(
            self.ROW, self.IDENTITY, self.PROFILE, campaign,
            website_text="Acme builds vague things for many teams.",
            personalization_facts="Acme provides invoice automation for finance teams.",
        )
        assert "verified facts" in prompt.lower()
        assert "invoice automation" in prompt
        assert "vague things" not in prompt

    def test_garbled_website_text_excluded(self):
        campaign = {"title": "Test", "description": "We do X", "pitch": "Try X"}
        prompt = build_user_prompt(
            self.ROW, self.IDENTITY, self.PROFILE, campaign,
            website_text="abc",  # too short
        )
        assert "website content" not in prompt.lower()
        assert "your own knowledge" in prompt.lower()

    def test_no_website_text_uses_own_knowledge(self):
        campaign = {"title": "Test", "description": "We do X", "pitch": "Try X"}
        prompt = build_user_prompt(self.ROW, self.IDENTITY, self.PROFILE, campaign)
        assert "your own knowledge" in prompt.lower()

    def test_always_includes_output_reminder(self):
        campaign = {"title": "Test", "description": "We do X", "pitch": "Try X"}
        prompt = build_user_prompt(self.ROW, self.IDENTITY, self.PROFILE, campaign)
        assert "subject line" in prompt.lower()

    def test_includes_structure_hint(self):
        campaign = {"title": "Test", "description": "We do X", "pitch": "Try X"}
        prompt = build_user_prompt(self.ROW, self.IDENTITY, self.PROFILE, campaign)
        assert "STRUCTURE:" in prompt

    def test_different_emails_get_different_structures(self):
        structures = set()
        for email in ["a@x.com", "b@y.com", "c@z.com", "d@w.com", "e@v.com",
                       "f@u.com", "g@t.com", "h@s.com", "i@r.com", "j@q.com"]:
            structures.add(_pick_structure(email))
        # With 10 emails and 5 structures, we should hit at least 2 different ones
        assert len(structures) >= 2

    def test_structure_is_deterministic(self):
        s1 = _pick_structure("alice@acme.com")
        s2 = _pick_structure("alice@acme.com")
        assert s1 == s2

    def test_bans_self_intro_pattern(self):
        campaign = {"title": "Test", "description": "We do X", "pitch": "Try X"}
        prompt = build_user_prompt(self.ROW, self.IDENTITY, self.PROFILE, campaign)
        assert "Do NOT start any paragraph with" in prompt


class TestBuildTemplatePrompt:
    ROW = {
        "first_name": "Alice",
        "last_name": "Smith",
        "company": "Acme",
        "email": "alice@acme.com",
    }

    def test_contains_recipient(self):
        identity = {"name": "Bob"}
        profile = {}
        prompt = build_template_prompt(self.ROW, identity, profile)
        assert "Alice Smith" in prompt
        assert "Acme" in prompt

    def test_uses_placeholder_without_name(self):
        prompt = build_template_prompt(self.ROW, {}, {})
        assert "[Your Name]" in prompt

    def test_includes_output_constraints(self):
        prompt = build_template_prompt(self.ROW, {"name": "X"}, {})
        assert "ONLY the email body" in prompt
        assert "80 words" in prompt
