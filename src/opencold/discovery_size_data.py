from __future__ import annotations

import re

_SIZE_BAND_RE = re.compile(
    r"(\d[\d,\.]*)\s*\+?\s*(?:employees|staff|people|team members)", re.IGNORECASE
)

_SME_HINT_RE = re.compile(
    r"\b(family[- ]owned|family business|since \d{4}|founded in \d{4}|small team|boutique)\b",
    re.IGNORECASE,
)
