"""Shared constants and patterns for company and contact discovery."""

import re

BLOCKED_DOMAINS = {
    "apple.com",
    "apps.apple.com",
    "cdn.jsdelivr.net",
    "cloudflare.com",
    "facebook.com",
    "github.com",
    "github.io",
    "google.com",
    "googletagmanager.com",
    "instagram.com",
    "linkedin.com",
    "maps.google.com",
    "medium.com",
    "notion.site",
    "reddit.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}

BLOCKED_HOST_PARTS = (
    "accounts.",
    "api.",
    "app.",
    "blog.",
    "cdn.",
    "docs.",
    "help.",
    "login.",
    "status.",
    "support.",
)

INTERNAL_SKIP_PARTS = (
    "about",
    "account",
    "advertise",
    "blog",
    "category",
    "contact",
    "cookie",
    "login",
    "privacy",
    "submit",
    "sign-in",
    "signin",
    "sign-up",
    "signup",
    "tag",
    "terms",
)

INTERNAL_DETAIL_HINTS = (
    "/ai/",
    "/app/",
    "/apps/",
    "/company/",
    "/companies/",
    "/directory/",
    "/product/",
    "/products/",
    "/startup/",
    "/startups/",
    "/tool/",
    "/tools/",
)

ROLE_PREFIXES = {
    "contact",
    "founders",
    "growth",
    "hello",
    "hi",
    "info",
    "marketing",
    "partner",
    "partnerships",
    "press",
    "product",
    "sales",
    "security",
    "support",
    "team",
    "vulnerability-disclosure",
    "responsible-disclosure",
    "abuse",
    "admin",
    "billing",
    "careers",
    "compliance",
    "enquiries",
    "enquiry",
    "feedback",
    "general",
    "help",
    "hr",
    "jobs",
    "legal",
    "media",
    "newsletter",
    "noreply",
    "no-reply",
    "office",
    "postmaster",
    "pr",
    "privacy",
    "webmaster",
}

GUESSED_ROLE_EMAILS = ("hello", "contact", "sales", "partnerships")

HIGH_VALUE_ROLE_PREFIXES = {
    "partnerships",
    "partner",
    "growth",
    "marketing",
    "product",
    "sales",
    "team",
}

LOW_VALUE_ROLE_PREFIXES = {
    "founders",
    "hello",
    "hi",
    "contact",
    "press",
    "support",
    "info",
}

# Role inboxes useless for cold outreach — these go to support queues, not decision makers
OUTREACH_USELESS_PREFIXES = {
    "support",
    "contact",
    "info",
    "hello",
    "hi",
    "help",
    "noreply",
    "no-reply",
    "admin",
    "webmaster",
    "press",
    "media",
    "abuse",
    "postmaster",
    "billing",
    "legal",
    "security",
    "privacy",
    "compliance",
    "feedback",
    "newsletter",
    "jobs",
    "careers",
    "hr",
    "office",
    "general",
    "enquiries",
    "enquiry",
    "pr",
    "vulnerability-disclosure",
    "responsible-disclosure",
}

RELEVANT_ROLE_RE = re.compile(
    r"\b("
    r"partnerships?|partner|growth|marketing|product marketing|"
    r"developer relations|devrel|community|sales|business development|"
    r"customer success|recruiting|talent|engineering|developer advocate"
    r")\b",
    re.IGNORECASE,
)

EXEC_ROLE_RE = re.compile(r"\b(founder|co-founder|ceo|cto|cfo|coo|president)\b", re.IGNORECASE)

DISCOVERY_PATHS = (
    "",
    "/about",
    "/contact",
    "/team",
    "/founders",
    "/company",
    "/press",
    "/security",
    "/legal",
    "/imprint",
    "/careers",
)

SEARCH_QUERIES = (
    "site:{domain} contact",
    "site:{domain} team OR people",
    "site:{domain} partnerships OR partner",
    "site:{domain} developer relations OR devrel",
    "site:{domain} growth OR marketing",
    '"{company}" "{domain}" email',
)

SEARCH_RESULT_LIMIT = 8
SEARCH_PAGE_LIMIT = 4
SEARCH_FETCH_MULTIPLIER = 3
SEARCH_TIMEOUT = 3.0

# LinkedIn contact discovery via DuckDuckGo search result titles.
LINKEDIN_SEARCH_QUERIES = (
    '"{company}" marketing manager site:linkedin.com/in',
    '"{company}" partnerships site:linkedin.com/in',
    '"{company}" head of growth site:linkedin.com/in',
    '"{company}" customer success site:linkedin.com/in',
    '"{company}" business development site:linkedin.com/in',
    '"{company}" developer relations site:linkedin.com/in',
    '"{company}" sales manager site:linkedin.com/in',
    '"{company}" community manager site:linkedin.com/in',
)

LINKEDIN_TITLE_RE = re.compile(
    r"^(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*[-\u2013\u2014]\s*"
    r"(?P<role>[^|\u2013\u2014]+?)\s*[-\u2013\u2014]\s*(?P<company>[^|]+?)\s*\|\s*LinkedIn",
)

LINKEDIN_TARGET_ROLES_RE = re.compile(
    r"(?i:market|partner|growth|customer success|business develop|"
    r"developer relat|devrel|community|sales|account|outreach|demand gen|"
    r"talent|recruiting|people ops)",
)

_LINKEDIN_QUERY_DELAY = 1.5
_LINKEDIN_MAX_QUERIES = 3
_VERIFY_EMPLOYMENT = True

# Patterns indicating someone moved to a different company.
# Company name group: one or more capitalized words (e.g. "HubSpot", "Acme Corp").
# Stops at lowercase words, digits-only tokens, or punctuation.
_COMPANY_NAME_PAT = r"[A-Z][A-Za-z0-9]*(?:\s+(?:[A-Z&][A-Za-z0-9]*|[A-Z]+))*"
_MOVED_PATTERNS = re.compile(
    r"(?:"
    rf"[Nn]ow\s+(?:at|with|@)\s+(?P<new1>{_COMPANY_NAME_PAT})"
    rf"|[Jj]oined\s+(?P<new2>{_COMPANY_NAME_PAT})"
    rf"|[Mm]oved\s+to\s+(?P<new3>{_COMPANY_NAME_PAT})"
    rf"|[Cc]urrently\s+(?:at|with|@)\s+(?P<new4>{_COMPANY_NAME_PAT})"
    r")"
)
_NOT_EMPLOYED_RE = re.compile(
    r"(?i:opentowork|open to work|laid off|looking for|seeking.*opportunit|between roles|"
    r"available for hire|freelanc|independent consultant)",
)

# Matches LinkedIn date ranges like "Jan 2023 - Present", "Mar 2021 - Dec 2023"
_EMPLOYMENT_DATE_RE = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{4})"
    r"\s*[-–—]\s*"
    r"(Present|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})",
    re.IGNORECASE,
)

# SearXNG public instances to try (rotated for load distribution)
_SEARXNG_INSTANCES = (
    "https://search.sapti.me",
    "https://searx.be",
    "https://searxng.site",
)

COMPANY_SUFFIXES_RE = re.compile(
    r"\s*\b(inc\.?|ltd\.?|llc\.?|corp\.?|co\.?|plc\.?|gmbh|s\.?a\.?|"
    r"pvt\.?\s*ltd\.?|limited|incorporated|corporation|company)\s*$",
    re.IGNORECASE,
)

SEARCH_PATH_HINTS = (
    "about",
    "business-development",
    "careers",
    "community",
    "company",
    "contact",
    "developer",
    "developers",
    "devrel",
    "growth",
    "marketing",
    "partners",
    "partnership",
    "partnerships",
    "people",
    "press",
    "sales",
    "security",
    "team",
)

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")
CTA_TEXT = re.compile(
    r"^(visit|visit website|website|open|learn more|view|go|launch|try it|demo)\s*(→|->)?$",
    re.IGNORECASE,
)
PERSON_LOCAL_RE = re.compile(r"^[a-z]+([._\-][a-z]+)?$")
PERSON_HINT_RE = re.compile(
    r"\b(?P<role>(?i:founder|co-founder|ceo|cto|cfo|coo|cpo|president|"
    r"head of [a-z]+|vp of [a-z]+|director of [a-z]+|"
    r"developer relations|devrel|growth|marketing|product|partnerships?|"
    r"community|sales|business development|customer success|recruiting|talent))"
    r"\b[:\s,-]+(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
)
PERSON_REVERSE_HINT_RE = re.compile(
    r"\b(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})"
    r"\b[,:\s-]+(?P<role>(?i:founder|co-founder|ceo|cto|cfo|coo|cpo|president|"
    r"head of [a-z]+|vp of [a-z]+|director of [a-z]+|"
    r"developer relations|devrel|growth|marketing|product|partnerships?|"
    r"community|sales|business development|customer success|recruiting|talent))\b",
)
BAD_PERSON_WORDS = {
    "About",
    "All",
    "And",
    "Careers",
    "Company",
    "Contact",
    "Co",
    "Home",
    "Legal",
    "Needle",
    "Press",
    "Privacy",
    "Processing",
    "Read",
    "Run",
    "Security",
    "Support",
    "Team",
    "Terms",
    "The",
    "We",
}
NOISY_PRODUCT_RE = re.compile(
    r"\b("
    r"directory|directories|backlink|submit your|submit ai|resume|cv|"
    r"video generator|audio tool|vocal remover|asmr|karaoke|wallpaper|"
    r"headshot|logo generator|image generator|tiktok|instagram"
    r")\b",
    re.IGNORECASE,
)
B2B_SIGNAL_RE = re.compile(
    r"\b("
    r"api|developer|developers|engineering|observability|analytics|crm|"
    r"workflow|workflows|infrastructure|security|database|data|agent|agents|"
    r"sdk|cloud|enterprise|saas|support|automation|billing|auth|monitoring"
    r")\b",
    re.IGNORECASE,
)
