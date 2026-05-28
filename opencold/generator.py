"""Multi-provider email generation (Anthropic, OpenAI, proxy)."""

import time

import anthropic

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 1024

# ── Provider auto-detection from model name ──────────────────────────────────

_MODEL_PREFIX_MAP = {
    "claude-": "anthropic",
    "gpt-": "openai",
    "o1-": "openai",
    "o3-": "openai",
    "o4-": "openai",
    "chatgpt-": "openai",
}


def detect_provider_for_model(model: str, providers: dict) -> str | None:
    """Auto-detect provider name from model string.

    Returns the provider name or None if no match.
    """
    # Check known prefixes
    for prefix, provider_type in _MODEL_PREFIX_MAP.items():
        if model.startswith(prefix):
            # Find a configured provider of this type
            for name, prov in providers.items():
                if prov.get("type") == provider_type:
                    return name
            return None

    # No prefix match — check if any proxy provider has this as its default model
    for name, prov in providers.items():
        if prov.get("type") == "proxy" and prov.get("default_model") == model:
            return name

    return None


# ── Anthropic generation ─────────────────────────────────────────────────────


def create_client(api_key: str | None = None) -> anthropic.Anthropic:
    """Create an Anthropic client (kept for backward compatibility)."""
    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    return anthropic.Anthropic(**kwargs)


def _generate_anthropic(
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return next(
        (block.text for block in response.content if block.type == "text"), ""
    )


# ── OpenAI / Proxy generation ────────────────────────────────────────────────


def _generate_openai(
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    model: str = "gpt-4o",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    base_url: str | None = None,
) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError(
            "OpenAI package is required for this provider. "
            "Install it with: pip install openai"
        )

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content or ""


# ── Post-processing (strip meta-commentary from weak models) ─────────────────

import re

_META_PATTERNS = [
    re.compile(r"\n\n(?:This response|This email|Here is|I hope this|Let me know if|Note:).*", re.DOTALL | re.IGNORECASE),
    re.compile(r"\n\n(?:The above|I've (?:written|crafted|composed)|Word count).*", re.DOTALL | re.IGNORECASE),
    re.compile(r"\n\n\[.*?\]$", re.DOTALL),  # bracketed notes at end
]

# Patterns that indicate leaked system/config data in a paragraph
_LEAK_INDICATORS = re.compile(
    r"(?:"
    r"\w+_\w+\s*[:=]"           # key_name: value or key_name= value
    r"|/[a-z]/\d+/"             # file paths like /u/26/75/
    r"|\.json\b"               # JSON file references
    r"|max_tokens|temperature|top_[kp]|frequency"  # LLM params
    r"|system_name|binary_name|latency|cache"      # system params
    r"|PARAMS\s*:"              # explicit params block
    r")",
    re.IGNORECASE,
)


def _is_leaked_paragraph(para: str) -> bool:
    """Detect if a paragraph contains leaked system/config data."""
    lines = para.strip().split("\n")
    if not lines:
        return False
    # If most lines look like key:value pairs, it's a leak
    kv_lines = sum(1 for line in lines if re.match(r"^\s*[\w./]+\s*[:=]", line.strip()))
    if kv_lines >= 2:
        return True
    # If it contains multiple leak indicators
    matches = _LEAK_INDICATORS.findall(para)
    if len(matches) >= 2:
        return True
    return False


def _clean_output(text: str) -> str:
    """Strip meta-commentary, leaked data, and formatting issues from model output."""
    text = text.strip()
    # Strip surrounding double quotes models sometimes wrap the email in
    text = text.strip('"')
    text = text.strip()
    # Remove double quotes from the body (keep apostrophes for contractions)
    text = text.replace('"', '')
    # Replace em/en dashes with commas (looks less AI-generated)
    text = text.replace('—', ',').replace('–', ',')
    # Clean up double commas or comma-space-comma from dash replacement
    text = re.sub(r',\s*,', ',', text)
    for pattern in _META_PATTERNS:
        text = pattern.sub("", text)
    # Remove leading "Subject:" or greeting lines some models prepend
    text = re.sub(r"^Subject:.*?\n+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(Dear|Hi|Hello|Hey)\s+\w+[,.]?\s*\n+", "", text, flags=re.IGNORECASE)
    # Standalone name greeting like "James,\n"
    text = re.sub(r"^\w+[,.]?\s*\n\n", "", text)
    # Remove trailing separators (---, ***, ===, etc.)
    text = re.sub(r"\s*[-*=]{3,}\s*$", "", text)
    # Remove trailing sign-off names like (Mehmet), (Name), - Mehmet, Best, Name
    text = re.sub(r"\n+\([\w\s]+\)\s*$", "", text)
    text = re.sub(r"\n+[-–—]\s*[\w\s]+\s*$", "", text)
    text = re.sub(r"\n+(?:Best|Regards|Cheers|Thanks|Thank you|Sincerely|Warm regards)[,.]?\s*\n*[\w\s]*$", "", text, flags=re.IGNORECASE)

    # Split into paragraphs, keep only clean ones (max 3)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    clean_paragraphs = []
    for para in paragraphs:
        if _is_leaked_paragraph(para):
            break  # Stop at first leaked paragraph — everything after is garbage
        clean_paragraphs.append(para)
        if len(clean_paragraphs) == 3:
            break  # Email should be exactly 3 paragraphs

    if clean_paragraphs:
        return "\n\n".join(clean_paragraphs)
    return text.strip()


def _clean_subject(subject: str) -> str:
    """Clean up a generated subject line."""
    subject = subject.strip().strip('"').strip("'")
    # Remove em/en dashes
    subject = subject.replace('—', ',').replace('–', ',')
    subject = re.sub(r',\s*,', ',', subject)
    # Strip trailing punctuation that looks weird in subject
    subject = subject.rstrip('.')
    return subject


# ── Subject/body splitting ───────────────────────────────────────────────────


def _split_subject_body(text: str) -> tuple[str, str]:
    """Split model output into (subject, body).

    Expected format: first line is subject, blank line, then body.
    Handles common model quirks: 'Subject: ' prefix, no blank line, etc.
    """
    text = text.strip()

    # Try splitting on first blank line
    if "\n\n" in text:
        first, rest = text.split("\n\n", 1)
    elif "\n" in text:
        first, rest = text.split("\n", 1)
    else:
        # Single block — no subject line, treat whole thing as body
        return "", text

    first = first.strip()
    rest = rest.strip()

    # Strip common prefixes models prepend
    for prefix in ("Subject:", "Subject Line:", "SUBJECT:", "Re:"):
        if first.lower().startswith(prefix.lower()):
            first = first[len(prefix):].strip()

    # Sanity check: if "subject" is too long, it's probably body text
    if len(first.split()) > 12:
        return "", text

    return first, rest


# ── Unified interface ────────────────────────────────────────────────────────


def generate_email(
    provider_config: dict,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    max_tokens: int | None = None,
) -> dict:
    """Generate an email using the specified provider configuration.

    Returns {"subject": str, "body": str}.

    provider_config: {"type": "anthropic"|"openai"|"proxy", "api_key": "...",
                      "default_model": "...", "base_url": "...", "max_tokens": N}
    """
    provider_type = provider_config.get("type", "anthropic")
    api_key = provider_config["api_key"]
    effective_model = model or provider_config.get("default_model") or DEFAULT_MODEL

    # Priority: explicit arg > provider config > default
    effective_max_tokens = max_tokens or provider_config.get("max_tokens") or DEFAULT_MAX_TOKENS

    if provider_type == "anthropic":
        raw = _generate_anthropic(api_key, system_prompt, user_prompt, effective_model, effective_max_tokens)
    elif provider_type in ("openai", "proxy"):
        base_url = provider_config.get("base_url") if provider_type == "proxy" else None
        raw = _generate_openai(api_key, system_prompt, user_prompt, effective_model, effective_max_tokens, base_url)
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")

    subject, body = _split_subject_body(raw)
    return {"subject": _clean_subject(subject), "body": _clean_output(body)}


def generate_with_retry(
    provider_config: dict,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    max_tokens: int | None = None,
) -> dict:
    """Generate with a single retry on rate-limit errors. Returns {"subject": str, "body": str}."""
    try:
        return generate_email(provider_config, system_prompt, user_prompt, model, max_tokens)
    except anthropic.RateLimitError:
        time.sleep(10)
        return generate_email(provider_config, system_prompt, user_prompt, model, max_tokens)
    except Exception as e:
        if "rate" in str(e).lower():
            time.sleep(10)
            return generate_email(provider_config, system_prompt, user_prompt, model, max_tokens)
        raise
