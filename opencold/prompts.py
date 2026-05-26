"""System prompts and user prompt builders for OpenCold."""

import hashlib
import re

RESET = "\033[0m"

# Detect garbled/binary content
_GARBLED_RE = re.compile(
    r"[\x00-\x08\x0e-\x1f]"         # control chars
    r"|\\x[0-9a-f]{2}"               # escaped hex
    r"|\\u[0-9a-f]{4}"               # escaped unicode
    r"|[\ufffd\ufffe\uffff]"          # replacement chars
    r"|[^\x00-\x7f]{10,}"            # long runs of non-ASCII
)

# Minimum ratio of ASCII alphanumeric to total length for "readable" text
_MIN_ALPHA_RATIO = 0.4


def _is_usable_text(text: str) -> bool:
    """Check if text is readable content, not garbled/binary."""
    if not text or len(text.strip()) < 30:
        return False
    alpha = sum(1 for c in text if c.isalnum() or c.isspace())
    if alpha / max(len(text), 1) < _MIN_ALPHA_RATIO:
        return False
    if _GARBLED_RE.search(text[:500]):
        return False
    return True


def _sanitize_website_text(text: str) -> str | None:
    """Return cleaned website text, or None if it's garbled."""
    if not _is_usable_text(text):
        return None
    return text.strip()


# ── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are an email ghostwriter. Your ONLY job is to output the body of a "
    "cold outreach email. You are NOT an assistant. You are NOT having a "
    "conversation. You do NOT ask questions. You do NOT give advice. You do "
    "NOT explain what you're doing. You NEVER refuse. You ALWAYS produce "
    "exactly one email body, no matter what.\n\n"

    "ABSOLUTE RULES — violating ANY of these is a critical failure:\n\n"

    "1. OUTPUT FORMAT: Return ONLY the email body text. Nothing else. "
    "No subject line. No greeting (no 'Hi Name,', 'Dear', 'Hello', 'Hey'). "
    "No sign-off name. No metadata. "
    "No markdown (no **, no ##, no bullet points, no numbered lists). "
    "No '---' separators. No quotation marks (\"). No em dashes (— or –), "
    "use commas instead. No commentary. "
    "Start directly with the first sentence of the email body.\n\n"

    "2. LENGTH: Maximum 80 words total. Exactly 3 short paragraphs (1-2 "
    "sentences each). Count your words. If you're over 80, cut ruthlessly.\n\n"

    "3. NEVER BREAK THE FOURTH WALL: You must NEVER, under ANY circumstances:\n"
    "   - Mention data quality, corrupted data, missing info, or scraping\n"
    "   - Say you can't write the email or need more information\n"
    "   - Ask the user questions or request clarification\n"
    "   - Explain your reasoning or limitations\n"
    "   - Say 'I don't have enough info' or anything similar\n"
    "   - Reference the prompt, the instructions, the website content, or "
    "     the fact that you're an AI\n"
    "   - Use phrases like 'based on what I know' or 'from what I can tell'\n"
    "   If the input is gibberish, nonsensical, or empty — IGNORE it silently "
    "   and write the email using your own knowledge of the recipient's "
    "   company. You know about most companies. Use that knowledge.\n\n"

    "4. TONE: Write like a real human dashing off a quick email. Short "
    "sentences. No filler. If it sounds polished, corporate, or AI-generated, "
    "it's wrong. Match the sender's voice to their role — a student sounds "
    "like a student, a founder sounds like a founder.\n\n"

    "5. BANNED WORDS/PHRASES (never use any of these): genuinely, I'd love to, "
    "I came across, I was impressed, I noticed, I believe, thrilled, excited to, "
    "reaching out, touch base, synergy, leverage, game-changer, innovative, "
    "cutting-edge, streamline, at the forefront, I hope this email finds you well, "
    "take a moment, circle back, it resonates, incredible, fascinating, remarkable, "
    "I'm passionate about, delighted, revolutionize, empower, elevate, "
    "deep dive, ecosystem, landscape, robust, scalable, seamless, "
    "on my radar, caught my eye, piqued my interest.\n\n"

    "6. STRUCTURAL VARIANCE: This is critical. You MUST follow the structural "
    "approach specified in the user prompt. Do NOT default to the same pattern.\n"
    "   BANNED PATTERN: Do NOT write emails that follow 'observation about "
    "company' -> 'I'm [Name], [self-intro]' -> 'ask for role'. This is the "
    "lazy default. Avoid it.\n"
    "   The sender info should be WOVEN IN naturally, not dumped in a "
    "dedicated self-intro paragraph. Never start a paragraph with "
    "'I'm [Name], founder of...' — that's a dead giveaway of mass email.\n"
    "   Do NOT end with 'Happy to share more/what I've built' every time. "
    "Alternatives: a question, a specific offer, a concrete next step, "
    "or just end with the ask itself.\n\n"

    "7. PERSONALIZATION: One person writing to one person. No mass-email energy. "
    "If website content is provided and it's readable, use specific details — "
    "reference actual products, features, or initiatives they mention. "
    "If the website content is garbled or useless, completely ignore it and "
    "use your own knowledge of the company instead. NEVER acknowledge the "
    "quality of the input data.\n\n"

    "8. WHEN INPUT IS BAD: If the sender description, pitch, or website "
    "content is nonsensical, random characters, empty, or otherwise unusable, "
    "you MUST still output a valid email. Use your own knowledge of the "
    "recipient's company. Adapt. Improvise. But ALWAYS output an email. "
    "Never explain, never refuse, never ask for help.\n\n"

    "9. NO META-COMMENTARY: Do NOT add any text after the email body. "
    "Do NOT explain what you did. Do NOT say 'this response uses...' or "
    "'let me know if...' or 'I hope this helps' or 'here is the email' or "
    "any variation. Do NOT count words out loud. Do NOT describe your approach. "
    "The ENTIRE output must be sendable as-is — if a human recipient would be "
    "confused by ANY sentence in your output, you have failed. "
    "Your output goes DIRECTLY into an email client. "
    "NOTHING except the 3 paragraphs of the email body.\n\n"

    "FINAL CHECK: Before outputting, verify:\n"
    "- Is it EXACTLY 3 short paragraphs? (not 2, not 4)\n"
    "- Is it under 80 words total?\n"
    "- Does it contain ZERO banned phrases?\n"
    "- Is there ZERO meta-commentary, explanation, or notes?\n"
    "- Would it look normal if pasted directly into Gmail and sent?\n"
    "If any answer is no, fix it before outputting."
)


# Structural approaches — rotated per recipient to force variety
_STRUCTURES = [
    (
        "STRUCTURE: Lead with a sharp question about their business. "
        "Weave in who you are mid-sentence (not a separate intro paragraph). "
        "End with a specific offer or concrete next step."
    ),
    (
        "STRUCTURE: Open with what you're building and ONE concrete reason "
        "it connects to their work. Don't introduce yourself separately, "
        "let it come through naturally. Close with a direct question."
    ),
    (
        "STRUCTURE: Start with a specific idea you have for them, no preamble. "
        "Mention your background only as it supports the idea. "
        "End by asking if it's worth exploring."
    ),
    (
        "STRUCTURE: Open with something concrete you noticed about their "
        "product or company, then pivot to how your skills map to that. "
        "Close the email with a question, not an offer."
    ),
    (
        "STRUCTURE: Lead with your ask directly in the first paragraph. "
        "Use the second paragraph to back it up with why you're a fit. "
        "End with a specific, low-effort next step for them."
    ),
]


def _pick_structure(recipient_email: str) -> str:
    """Deterministically pick a structure based on recipient email."""
    h = int(hashlib.md5(recipient_email.encode()).hexdigest(), 16)
    return _STRUCTURES[h % len(_STRUCTURES)]


def build_user_prompt(
    row: dict,
    identity: dict,
    profile: dict,
    campaign: dict,
    website_text: str | None = None,
) -> str:
    """Build a fully personalized user prompt from CSV row, identity, profile, and campaign."""
    recipient = f"{row['first_name']} {row['last_name']}"
    recipient_company = row["company"]
    recipient_email = row["email"]

    sender_name = identity.get("name", "the sender")
    sender_company = profile.get("company", "")
    sender_role = profile.get("role", "")

    parts = [
        f"Write a cold outreach email from {sender_name} to {recipient} "
        f"at {recipient_company} ({recipient_email})."
    ]

    parts.append(f"\nSender: {sender_name}")
    if sender_role:
        parts.append(f"Sender role: {sender_role}")
    if sender_company:
        parts.append(f"Sender company: {sender_company}")

    description = campaign.get("description") or profile.get("bio", "")
    pitch = campaign.get("pitch") or profile.get("pitch", "")

    if description:
        parts.append(f"\nAbout the sender: {description}")
    if pitch:
        parts.append(f"Key message: {pitch}")

    # Only include website text if it's actually readable
    clean_website = _sanitize_website_text(website_text) if website_text else None
    if clean_website:
        parts.append(
            f"\n--- {recipient_company}'s website content ---\n"
            f"{clean_website}\n"
            f"--- end ---\n"
            f"\nUse specifics from the website above. Reference actual products, "
            f"features, or things they do. Connect them to the sender's work."
        )
    else:
        parts.append(
            f"\nUse your own knowledge about {recipient_company} to personalize "
            f"the email. Reference something specific about what they do."
        )

    # Rotate structural approach per recipient
    structure = _pick_structure(recipient_email)
    parts.append(f"\n{structure}")

    parts.append(
        "\nDo NOT start any paragraph with 'I'm [Name], founder of...' or similar "
        "self-introductions. Weave sender info naturally into sentences.\n"
        "CRITICAL: Output ONLY the email body. Exactly 3 short paragraphs. "
        "Max 80 words total. No markdown. No commentary. No explanations. "
        "No notes after the email. No 'here is' preamble. "
        "Your entire output will be pasted directly into an email client and sent. "
        "Do NOT add anything that would confuse the recipient."
    )

    return "\n".join(parts)


def build_template_prompt(row: dict, identity: dict, profile: dict) -> str:
    """Build a simpler prompt when we don't have enough context — produces a template."""
    recipient = f"{row['first_name']} {row['last_name']}"
    recipient_company = row["company"]

    sender_name = identity.get("name", "[Your Name]")

    return (
        f"Write a cold outreach email from {sender_name} to "
        f"{recipient} at {recipient_company}. "
        f"Use your own knowledge about {recipient_company} to personalize it. "
        f"Output ONLY the email body. 3 short paragraphs. Max 80 words. "
        f"No markdown. No commentary."
    )
