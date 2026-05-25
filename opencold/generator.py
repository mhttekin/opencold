"""Claude API integration for email generation."""

import time

import anthropic

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 300


def create_client(api_key: str | None = None) -> anthropic.Anthropic:
    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    return anthropic.Anthropic(**kwargs)


def generate_email(
    client: anthropic.Anthropic,
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return next(
        (block.text for block in response.content if block.type == "text"), ""
    )


def generate_with_retry(
    client: anthropic.Anthropic,
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    try:
        return generate_email(client, system_prompt, user_prompt, model, max_tokens)
    except anthropic.RateLimitError:
        time.sleep(10)
        return generate_email(client, system_prompt, user_prompt, model, max_tokens)
