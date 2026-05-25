"""Tests for prompts module."""

from opencold.prompts import (
    Category,
    SYSTEM_PROMPTS,
    build_user_prompt,
    build_template_prompt,
    category_label,
)


class TestCategory:
    def test_enum_values(self):
        assert Category.sales.value == "sales"
        assert Category.partnerships.value == "partnerships"
        assert Category.personal.value == "personal"

    def test_category_label_contains_value(self):
        label = category_label(Category.sales)
        assert "sales" in label
        assert "\u25cf" in label  # colored circle


class TestSystemPrompts:
    def test_all_categories_have_prompts(self):
        for cat in Category:
            assert cat in SYSTEM_PROMPTS
            assert len(SYSTEM_PROMPTS[cat]) > 100

    def test_prompts_contain_word_limit(self):
        for cat in Category:
            assert "80 words" in SYSTEM_PROMPTS[cat]

    def test_prompts_ban_genuinely(self):
        for cat in Category:
            prompt = SYSTEM_PROMPTS[cat].lower()
            assert "genuinely" in prompt  # it's in the ban list
            assert "never use" in prompt or "never" in prompt

    def test_prompts_forbid_meta_commentary(self):
        for cat in Category:
            assert "crawling" in SYSTEM_PROMPTS[cat].lower() or "data quality" in SYSTEM_PROMPTS[cat].lower()

    def test_prompts_require_variance(self):
        for cat in Category:
            assert "vary" in SYSTEM_PROMPTS[cat].lower()


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
        prompt = build_user_prompt(self.ROW, self.IDENTITY, self.PROFILE, Category.sales)
        assert "Alice Smith" in prompt
        assert "Acme" in prompt

    def test_contains_sender(self):
        prompt = build_user_prompt(self.ROW, self.IDENTITY, self.PROFILE, Category.sales)
        assert "Bob Builder" in prompt
        assert "BuildCo" in prompt
        assert "Founder" in prompt

    def test_uses_profile_bio_as_default(self):
        prompt = build_user_prompt(self.ROW, self.IDENTITY, self.PROFILE, Category.sales)
        assert "I build tools" in prompt
        assert "Automate everything" in prompt

    def test_context_overrides_profile(self):
        ctx = {"description": "We do AI", "pitch": "Try our AI"}
        prompt = build_user_prompt(self.ROW, self.IDENTITY, self.PROFILE, Category.sales, context=ctx)
        assert "We do AI" in prompt
        assert "Try our AI" in prompt
        assert "I build tools" not in prompt

    def test_website_text_included(self):
        prompt = build_user_prompt(
            self.ROW, self.IDENTITY, self.PROFILE, Category.sales,
            website_text="Acme builds rockets for Mars colonization.",
        )
        assert "Acme builds rockets" in prompt
        assert "website content" in prompt.lower()

    def test_no_website_text(self):
        prompt = build_user_prompt(self.ROW, self.IDENTITY, self.PROFILE, Category.sales)
        assert "website content" not in prompt.lower()


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
        prompt = build_template_prompt(self.ROW, identity, profile, Category.sales)
        assert "Alice Smith" in prompt
        assert "Acme" in prompt

    def test_uses_placeholder_without_name(self):
        prompt = build_template_prompt(self.ROW, {}, {}, Category.personal)
        assert "[Your Name]" in prompt

    def test_contains_category(self):
        prompt = build_template_prompt(self.ROW, {"name": "X"}, {}, Category.partnerships)
        assert "partnerships" in prompt
