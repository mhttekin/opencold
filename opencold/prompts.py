"""Category-specific system prompts and user prompt builders for OpenCold."""

from enum import Enum

RESET = "\033[0m"


class Category(str, Enum):
    sales = "sales"
    partnerships = "partnerships"
    personal = "personal"


# ● colored circles per category
CATEGORY_COLORS = {
    Category.sales: "\033[32m",        # green
    Category.partnerships: "\033[34m", # blue
    Category.personal: "\033[33m",     # yellow
}


def category_label(cat: Category) -> str:
    """Return '● category_name' with the category's color."""
    color = CATEGORY_COLORS[cat]
    return f"{color}\u25cf{RESET} {cat.value}"


# ── Voice & style rules shared across all categories ────────────────────────

_VOICE_RULES = (
    "\n\nSTYLE & VOICE RULES (non-negotiable):\n"
    "- MAX 80 words total. Exactly 3 tiny paragraphs (1-2 sentences each). "
    "Count your words. If you're over 80, cut ruthlessly.\n"
    "- Write like a real human dashing off a quick email. Short sentences. "
    "No filler. If it sounds polished or corporate, it's wrong.\n"
    "- NEVER use: genuinely, I'd love to, I came across, I was impressed, "
    "I noticed, I believe, thrilled, excited to, reaching out, touch base, "
    "synergy, leverage, game-changer, innovative, cutting-edge, streamline, "
    "at the forefront, I hope this email finds you well, take a moment, "
    "circle back, it resonates, incredible, fascinating, remarkable, "
    "I'm passionate about, delighted.\n"
    "- NEVER mention data quality, crawling, website scraping, or say things "
    "like 'the content came through corrupted' or 'based on limited info'. "
    "If you don't have enough info about a company, just write the email "
    "without acknowledging the gap. Never break the fourth wall.\n"
    "- VARY the structure. Do NOT follow 'intro → pitch → CTA' every time. "
    "Pick a DIFFERENT approach each email:\n"
    "  * A sharp question about something specific to their business.\n"
    "  * A one-line observation, then why you're writing.\n"
    "  * What you're building and one concrete reason it's relevant to them.\n"
    "  * Something you have in common, straight into the ask.\n"
    "  * A specific idea you have for them, no preamble.\n"
    "- Do NOT end with '15-minute call/chat' every time. Alternatives: "
    "a question, an offer to share something, a concrete next step, "
    "or just 'happy to share more'.\n"
    "- One person writing to one person. No mass-email energy.\n"
    "- Return ONLY the email body. No subject line, no sign-off name, "
    "no metadata, no markdown, no '---' separators.\n"
)


SYSTEM_PROMPTS = {
    Category.sales: (
        "You write cold outreach emails for B2B sales. You sound like a sharp, "
        "direct human — not a sales bot. You get to the point fast, show you "
        "understand the prospect's business, and make the connection to what "
        "the sender does feel natural, not forced. If website content about "
        "the recipient's company is provided, use specific details from it — "
        "don't just namedrop, actually tie it to something relevant."
        + _VOICE_RULES
    ),
    Category.partnerships: (
        "You write partnership outreach emails. You sound like someone who's "
        "thought about why this specific collaboration makes sense — not someone "
        "blasting templates. You focus on what both sides get out of it and "
        "reference real details about their work. If website content is provided, "
        "weave in specifics that show you actually explored what they do."
        + _VOICE_RULES
    ),
    Category.personal: (
        "You write personal networking emails. You sound like a curious, "
        "thoughtful human — someone who's done their homework and has a clear "
        "reason for reaching out. Match the sender's voice to their role: "
        "if they're a student, sound like a smart student, not a corporate exec. "
        "If they're a founder, sound like a founder. Be warm but not sycophantic. "
        "If website content is provided, reference something specific that "
        "connects to the sender's own interests or background."
        + _VOICE_RULES
    ),
}


def build_user_prompt(
    row: dict,
    identity: dict,
    profile: dict,
    category: Category,
    context: dict | None = None,
    website_text: str | None = None,
) -> str:
    """Build a fully personalized user prompt from CSV row, identity, profile, and context."""
    recipient = f"{row['first_name']} {row['last_name']}"
    recipient_company = row["company"]
    recipient_email = row["email"]

    sender_name = identity.get("name", "the sender")
    sender_company = profile.get("company", "")
    sender_role = profile.get("role", "")

    parts = [f"Write a cold outreach email from {sender_name} to {recipient} at {recipient_company} ({recipient_email})."]

    parts.append(f"\nSender: {sender_name}")
    if sender_role:
        parts.append(f"Sender role: {sender_role}")
    if sender_company:
        parts.append(f"Sender company: {sender_company}")

    # Use context overrides if provided, otherwise fall back to profile bio/pitch
    description = (context or {}).get("description") or profile.get("bio", "")
    pitch = (context or {}).get("pitch") or profile.get("pitch", "")

    if description:
        parts.append(f"\nAbout the sender: {description}")
    if pitch:
        parts.append(f"Key message: {pitch}")

    if website_text:
        parts.append(
            f"\n--- {recipient_company}'s website content ---\n"
            f"{website_text}\n"
            f"--- end ---\n"
            f"\nUse specifics from the website above. Don't just mention their company "
            f"name — reference actual products, features, or things they talk about, "
            f"and connect them to what the sender does or cares about. "
            f"Each email you write must be structurally different from others."
        )

    return "\n".join(parts)


def build_template_prompt(row: dict, identity: dict, profile: dict, category: Category) -> str:
    """Build a simpler prompt when we don't have enough context — produces a template."""
    recipient = f"{row['first_name']} {row['last_name']}"
    recipient_company = row["company"]

    sender_name = identity.get("name", "[Your Name]")

    return (
        f"Write a cold outreach email template from {sender_name} to "
        f"{recipient} at {recipient_company}. "
        f"Category: {category.value}. "
        f"Use [bracketed placeholders] for any specific details the sender "
        f"should fill in (e.g. [specific product benefit], [mutual connection])."
    )
