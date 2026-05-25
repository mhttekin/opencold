"""Tests for generator module (mocked API — no real calls)."""

from unittest.mock import patch, MagicMock
from opencold import generator


def _mock_response(text: str):
    """Create a mock Anthropic API response."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


class TestGenerateEmail:
    @patch("opencold.generator.anthropic.Anthropic")
    def test_returns_text(self, MockAnthropic):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("Hi Alice, great email here.")

        result = generator.generate_email(client, "system", "user prompt")
        assert result == "Hi Alice, great email here."

    @patch("opencold.generator.anthropic.Anthropic")
    def test_passes_params(self, MockAnthropic):
        client = MagicMock()
        client.messages.create.return_value = _mock_response("ok")

        generator.generate_email(
            client, "sys prompt", "user prompt",
            model="claude-haiku-4-5", max_tokens=200,
        )

        call_kwargs = client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-haiku-4-5"
        assert call_kwargs["max_tokens"] == 200
        assert call_kwargs["system"] == "sys prompt"
        assert call_kwargs["messages"][0]["content"] == "user prompt"


class TestGenerateWithRetry:
    @patch("opencold.generator.anthropic.Anthropic")
    def test_retries_on_rate_limit(self, MockAnthropic):
        import anthropic

        client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {}

        # First call raises RateLimitError, second succeeds
        client.messages.create.side_effect = [
            anthropic.RateLimitError(
                message="rate limited",
                response=mock_resp,
                body={"error": {"type": "rate_limit_error", "message": "rate limited"}},
            ),
            _mock_response("retry success"),
        ]

        with patch("opencold.generator.time.sleep"):
            result = generator.generate_with_retry(client, "sys", "user")
            assert result == "retry success"
            assert client.messages.create.call_count == 2


class TestCreateClient:
    @patch("opencold.generator.anthropic.Anthropic")
    def test_with_key(self, MockAnthropic):
        generator.create_client("sk-test")
        MockAnthropic.assert_called_once_with(api_key="sk-test")

    @patch("opencold.generator.anthropic.Anthropic")
    def test_without_key(self, MockAnthropic):
        generator.create_client()
        MockAnthropic.assert_called_once_with()


class TestDefaults:
    def test_default_model(self):
        assert "claude" in generator.DEFAULT_MODEL

    def test_default_max_tokens(self):
        assert generator.DEFAULT_MAX_TOKENS == 300
