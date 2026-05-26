"""Tests for generator module (mocked API — no real calls)."""

from unittest.mock import patch, MagicMock
from opencold import generator


def _mock_anthropic_response(text: str):
    """Create a mock Anthropic API response."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _mock_openai_response(text: str):
    """Create a mock OpenAI API response."""
    choice = MagicMock()
    choice.message.content = text
    resp = MagicMock()
    resp.choices = [choice]
    return resp


ANTHROPIC_CONFIG = {"type": "anthropic", "api_key": "sk-ant-test", "default_model": "claude-sonnet-4-6"}
OPENAI_CONFIG = {"type": "openai", "api_key": "sk-test", "default_model": "gpt-4o"}
PROXY_CONFIG = {"type": "proxy", "api_key": "sk-proxy", "default_model": "llama-3", "base_url": "https://proxy.test/v1"}


class TestGenerateEmail:
    @patch("opencold.generator.anthropic.Anthropic")
    def test_anthropic_returns_text(self, MockAnthropic):
        client = MagicMock()
        client.messages.create.return_value = _mock_anthropic_response("Hi Alice, great email here.")
        MockAnthropic.return_value = client

        result = generator.generate_email(ANTHROPIC_CONFIG, "system", "user prompt")
        assert result == "Hi Alice, great email here."

    @patch("opencold.generator.anthropic.Anthropic")
    def test_anthropic_passes_params(self, MockAnthropic):
        client = MagicMock()
        client.messages.create.return_value = _mock_anthropic_response("ok")
        MockAnthropic.return_value = client

        generator.generate_email(
            ANTHROPIC_CONFIG, "sys prompt", "user prompt",
            model="claude-haiku-4-5", max_tokens=200,
        )

        call_kwargs = client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-haiku-4-5"
        assert call_kwargs["max_tokens"] == 200
        assert call_kwargs["system"] == "sys prompt"
        assert call_kwargs["messages"][0]["content"] == "user prompt"

    @patch("opencold.generator._generate_openai")
    def test_openai_dispatch(self, mock_gen):
        mock_gen.return_value = "Hello from OpenAI"
        result = generator.generate_email(OPENAI_CONFIG, "sys", "user")
        assert result == "Hello from OpenAI"
        mock_gen.assert_called_once_with("sk-test", "sys", "user", "gpt-4o", 1024, None)

    @patch("opencold.generator._generate_openai")
    def test_proxy_dispatch_with_base_url(self, mock_gen):
        mock_gen.return_value = "Hello from proxy"
        result = generator.generate_email(PROXY_CONFIG, "sys", "user")
        assert result == "Hello from proxy"
        mock_gen.assert_called_once_with("sk-proxy", "sys", "user", "llama-3", 1024, "https://proxy.test/v1")

    @patch("opencold.generator._generate_openai")
    def test_proxy_uses_config_max_tokens(self, mock_gen):
        mock_gen.return_value = "Hello"
        proxy_cfg = {**PROXY_CONFIG, "max_tokens": 4096}
        generator.generate_email(proxy_cfg, "sys", "user")
        call_kwargs = mock_gen.call_args[0]
        assert call_kwargs[4] == 4096  # max_tokens arg

    @patch("opencold.generator._generate_openai")
    def test_explicit_max_tokens_overrides_config(self, mock_gen):
        mock_gen.return_value = "Hello"
        proxy_cfg = {**PROXY_CONFIG, "max_tokens": 4096}
        generator.generate_email(proxy_cfg, "sys", "user", max_tokens=8192)
        call_kwargs = mock_gen.call_args[0]
        assert call_kwargs[4] == 8192

    def test_unknown_type_raises(self):
        import pytest
        bad_config = {"type": "unknown", "api_key": "x", "default_model": "x"}
        with pytest.raises(ValueError, match="Unknown provider type"):
            generator.generate_email(bad_config, "sys", "user")

    @patch("opencold.generator.anthropic.Anthropic")
    def test_uses_default_model_from_config(self, MockAnthropic):
        client = MagicMock()
        client.messages.create.return_value = _mock_anthropic_response("ok")
        MockAnthropic.return_value = client

        generator.generate_email(ANTHROPIC_CONFIG, "sys", "user")
        call_kwargs = client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-6"


class TestGenerateWithRetry:
    @patch("opencold.generator.anthropic.Anthropic")
    def test_retries_on_rate_limit(self, MockAnthropic):
        import anthropic

        client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {}

        client.messages.create.side_effect = [
            anthropic.RateLimitError(
                message="rate limited",
                response=mock_resp,
                body={"error": {"type": "rate_limit_error", "message": "rate limited"}},
            ),
            _mock_anthropic_response("retry success"),
        ]
        MockAnthropic.return_value = client

        with patch("opencold.generator.time.sleep"):
            result = generator.generate_with_retry(ANTHROPIC_CONFIG, "sys", "user")
            assert result == "retry success"
            assert client.messages.create.call_count == 2


class TestDetectProvider:
    def test_claude_model(self):
        providers = {"anthropic": {"type": "anthropic"}, "openai": {"type": "openai"}}
        assert generator.detect_provider_for_model("claude-sonnet-4-6", providers) == "anthropic"
        assert generator.detect_provider_for_model("claude-opus-4-6", providers) == "anthropic"

    def test_gpt_model(self):
        providers = {"anthropic": {"type": "anthropic"}, "openai": {"type": "openai"}}
        assert generator.detect_provider_for_model("gpt-4o", providers) == "openai"
        assert generator.detect_provider_for_model("gpt-4o-mini", providers) == "openai"

    def test_o1_model(self):
        providers = {"openai": {"type": "openai"}}
        assert generator.detect_provider_for_model("o1-preview", providers) == "openai"

    def test_proxy_model_by_default(self):
        providers = {"myproxy": {"type": "proxy", "default_model": "llama-3"}}
        assert generator.detect_provider_for_model("llama-3", providers) == "myproxy"

    def test_unknown_model_returns_none(self):
        providers = {"anthropic": {"type": "anthropic"}}
        assert generator.detect_provider_for_model("some-random-model", providers) is None

    def test_no_matching_provider_type(self):
        providers = {"myproxy": {"type": "proxy"}}
        # claude prefix but no anthropic provider configured
        assert generator.detect_provider_for_model("claude-sonnet-4-6", providers) is None


class TestCreateClient:
    @patch("opencold.generator.anthropic.Anthropic")
    def test_with_key(self, MockAnthropic):
        generator.create_client("sk-test")
        MockAnthropic.assert_called_once_with(api_key="sk-test")

    @patch("opencold.generator.anthropic.Anthropic")
    def test_without_key(self, MockAnthropic):
        generator.create_client()
        MockAnthropic.assert_called_once_with()


class TestCleanOutput:
    def test_strips_meta_commentary(self):
        text = (
            "First paragraph here.\n\n"
            "Second paragraph.\n\n"
            "Third paragraph.\n\n"
            "This response uses my knowledge of Linear to personalize the email."
        )
        result = generator._clean_output(text)
        assert "This response" not in result
        assert "Third paragraph." in result

    def test_strips_let_me_know(self):
        text = "Para 1.\n\nPara 2.\n\nPara 3.\n\nLet me know if you would like me to modify this."
        result = generator._clean_output(text)
        assert "Let me know" not in result

    def test_strips_subject_line(self):
        text = "Subject: Quick question\n\nThe actual email body here."
        result = generator._clean_output(text)
        assert "Subject:" not in result
        assert "actual email body" in result

    def test_strips_greeting(self):
        text = "Hi James,\n\nThe actual email starts here.\n\nSecond para.\n\nThird."
        result = generator._clean_output(text)
        assert "Hi James" not in result
        assert "actual email starts" in result

    def test_leaves_clean_email_alone(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        assert generator._clean_output(text) == text

    def test_strips_word_count_note(self):
        text = "Para 1.\n\nPara 2.\n\nPara 3.\n\n[Word count: 45]"
        result = generator._clean_output(text)
        assert "Word count" not in result

    def test_strips_trailing_dashes(self):
        text = "Para 1.\n\nPara 2.\n\nPara 3.\n\n---"
        result = generator._clean_output(text)
        assert "---" not in result
        assert "Para 3." in result

    def test_strips_trailing_dashes_with_spaces(self):
        text = "Para 1.\n\nPara 2.\n\nPara 3. \n\n ---  "
        result = generator._clean_output(text)
        assert "---" not in result
        assert "Para 3." in result

    def test_strips_signoff_name_in_parens(self):
        text = "Para 1.\n\nPara 2.\n\nPara 3.\n\n(Mehmet)"
        result = generator._clean_output(text)
        assert "Mehmet" not in result
        assert "Para 3." in result

    def test_strips_signoff_with_dash(self):
        text = "Para 1.\n\nPara 2.\n\nPara 3.\n\n- Mehmet"
        result = generator._clean_output(text)
        assert "Mehmet" not in result
        assert "Para 3." in result

    def test_strips_best_regards(self):
        text = "Para 1.\n\nPara 2.\n\nPara 3.\n\nBest,\nMehmet"
        result = generator._clean_output(text)
        assert "Best" not in result
        assert "Mehmet" not in result
        assert "Para 3." in result

    def test_strips_quotes(self):
        text = 'He said "hello" and she said \'goodbye\'.'
        result = generator._clean_output(text)
        assert '"' not in result
        assert "'" not in result
        assert "He said hello" in result

    def test_strips_wrapping_quotes(self):
        text = '"Para 1.\n\nPara 2.\n\nPara 3."'
        result = generator._clean_output(text)
        assert not result.startswith('"')
        assert not result.endswith('"')

    def test_strips_greeting_after_quote(self):
        text = '"Hi Emily,\n\nThe actual email body.\n\nSecond para.\n\nThird."'
        result = generator._clean_output(text)
        assert "Hi Emily" not in result
        assert "actual email body" in result

    def test_strips_standalone_name_greeting(self):
        text = "James,\n\nThe actual email starts here.\n\nSecond para.\n\nThird."
        result = generator._clean_output(text)
        assert "James" not in result
        assert "actual email starts" in result

    def test_strips_leaked_config_params(self):
        text = (
            "Great first paragraph.\n\n"
            "Second paragraph here.\n\n"
            "Third paragraph.\n\n"
            " kovg_PARAMS:\n"
            " kovg_language: ubuntu\n"
            " kovg_title: test\n"
            " kovg_max_tokens: 256\n"
            " kovg_temperature: 0.5"
        )
        result = generator._clean_output(text)
        assert "kovg" not in result
        assert "max_tokens" not in result
        assert "Third paragraph." in result

    def test_strips_leaked_system_paths(self):
        text = (
            "First para.\n\n"
            "Second para.\n\n"
            "Third para.\n\n"
            "system_name: test\n"
            "binary_name: foo\n"
            "/u/26/75/t179065.json"
        )
        result = generator._clean_output(text)
        assert "system_name" not in result
        assert ".json" not in result
        assert "Third para." in result

    def test_enforces_max_3_paragraphs(self):
        text = "Para 1.\n\nPara 2.\n\nPara 3.\n\nPara 4 extra.\n\nPara 5 extra."
        result = generator._clean_output(text)
        assert "Para 1." in result
        assert "Para 3." in result
        assert "Para 4" not in result
        assert "Para 5" not in result

    def test_keeps_valid_3_paragraphs(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        assert generator._clean_output(text) == text


class TestDefaults:
    def test_default_model(self):
        assert "claude" in generator.DEFAULT_MODEL

    def test_default_max_tokens(self):
        assert generator.DEFAULT_MAX_TOKENS == 1024
