"""Shared company contact patterns and email priorities."""

import re

_LINKEDIN_COMPANY_RE = re.compile(
    r"https?://[a-z]{0,3}\.?linkedin\.com/company/[A-Za-z0-9_%.\-]+", re.IGNORECASE
)
# Conservative phone matcher — international-ish, avoids matching long ID strings.
_PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d\s().\-]{6,16}\d)(?!\w)")

PARTNERSHIP_PATH_HINTS = (
    "partners",
    "partner",
    "partnership",
    "partnerships",
    "become-a-partner",
    "reseller",
    "resellers",
    "affiliate",
    "affiliates",
)

# Company-level email policy (the inverse of the person-finder): generic inboxes
# like info@/contact@ are KEPT — they are a legitimate first touch for partnership
# outreach. Partnership/BD inboxes rank highest.
COMPANY_EMAIL_PRIORITY = {
    "partnerships": 95,
    "partner": 93,
    "bd": 90,
    "business-development": 90,
    "growth": 86,
    "marketing": 84,
    "sales": 82,
    "hello": 70,
    "contact": 66,
    "info": 64,
    "enquiries": 62,
    "enquiry": 62,
    "team": 60,
    "press": 50,
    "media": 48,
    "support": 40,
}

_SOCIAL_HOSTS = (
    "linkedin.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
)
