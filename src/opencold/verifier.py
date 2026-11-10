"""Email verification via format check and MX record lookup."""

import re
import socket
import dns.resolver

# Basic email regex — intentionally simple, covers 99% of real addresses
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# Cache MX results per domain to avoid repeated lookups
_mx_cache: dict[str, bool] = {}


def _check_format(email: str) -> str | None:
    """Check email format. Returns error string or None if valid."""
    if not email or not email.strip():
        return "empty"
    if not _EMAIL_RE.match(email.strip()):
        return "invalid format"
    return None


def _check_mx(domain: str, timeout: float = 5.0) -> bool:
    """Check if domain has MX records. Results are cached per domain."""
    if domain in _mx_cache:
        return _mx_cache[domain]

    try:
        resolver = dns.resolver.Resolver()
        resolver.timeout = timeout
        resolver.lifetime = timeout
        answers = resolver.resolve(domain, "MX")
        has_mx = len(answers) > 0
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN,
            dns.resolver.NoNameservers, dns.exception.Timeout,
            dns.resolver.LifetimeTimeout):
        has_mx = False
    except Exception:
        # DNS issue — don't block on transient errors
        has_mx = True  # assume valid on unexpected errors

    _mx_cache[domain] = has_mx
    return has_mx


def verify_email(email: str) -> dict:
    """Verify a single email address.

    Returns {"email": str, "valid": bool, "reason": str}.
    """
    email = email.strip()

    fmt_err = _check_format(email)
    if fmt_err:
        return {"email": email, "valid": False, "reason": fmt_err}

    domain = email.split("@")[1]

    if not _check_mx(domain):
        return {"email": email, "valid": False, "reason": f"no MX records for {domain}"}

    return {"email": email, "valid": True, "reason": "ok"}


def verify_emails(emails: list[str]) -> list[dict]:
    """Verify a batch of emails. Returns list of verification results."""
    return [verify_email(e) for e in emails]


def clear_cache() -> None:
    """Clear the MX cache (useful for testing)."""
    _mx_cache.clear()
