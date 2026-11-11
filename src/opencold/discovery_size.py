from __future__ import annotations

import re

from opencold.discovery_contact_model import CompanyContacts
from opencold.discovery_size_data import _SIZE_BAND_RE, _SME_HINT_RE


def size_tier(pages_text: str, contacts: CompanyContacts) -> str:
    """Coarse company-size band (micro|sme|mid|enterprise) from cheap signals.

    Best-effort — emitted as a filter column, not a hard gate."""
    text = pages_text or ""
    match = _SIZE_BAND_RE.search(text)
    if match:
        try:
            n = int(re.sub(r"\D", "", match.group(1)))
            if n >= 1000:
                return "enterprise"
            if n >= 200:
                return "mid"
            if n >= 20:
                return "sme"
            return "micro"
        except ValueError:
            pass
    if _SME_HINT_RE.search(text):
        return "sme"
    return ""
