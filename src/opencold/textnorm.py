"""Text folding for MATCHING only (never for values shown to the user).

fold() is the single comparison key used by region, ICP-evidence and name matching:
casefold -> NFKD -> drop combining marks, so "İZMİR" -> "izmir", "ÜRETİM" ->
"uretim", "São Paulo" -> "sao paulo". A few letters have no Unicode decomposition
(Turkish dotless ı, Polish ł, Nordic ø, đ) and are transliterated explicitly, so
"Abatıneva" folds to the same key as its ASCII domain "abatineva".
"""

from __future__ import annotations

import unicodedata

# Letters NFKD leaves intact (no combining-mark decomposition), mapped to the
# ASCII letter used when the word is written without diacritics.
_NO_DECOMP = str.maketrans({"ı": "i", "ł": "l", "ø": "o", "đ": "d"})


def fold(text: str) -> str:
    s = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(c for c in s if not unicodedata.combining(c)).translate(_NO_DECOMP)
