"""fold(): the single matching key (casefold -> NFKD -> strip combining marks)."""

import pytest

from opencold import discovery
from opencold.textnorm import fold


@pytest.mark.parametrize(
    "raw, folded",
    [
        ("İZMİR", "izmir"),
        ("ÜRETİM", "uretim"),
        ("São Paulo", "sao paulo"),
        ("Abatıneva", "abatineva"),
        ("Straße", "strasse"),
        ("", ""),
        (None, ""),
    ],
)
def test_fold(raw, folded):
    assert fold(raw) == folded


def test_icp_evidence_matches_across_case_and_diacritics():
    assert discovery._icp_match({"üretim"}, "Palet ÜRETİM tesisi") == ["üretim"]


def test_company_tokens_keep_turkish_letters():
    assert discovery._company_tokens("Şahinler Palet Ltd") == ["sahinler", "palet"]


def test_domain_matches_company_with_dotless_i():
    assert discovery._domain_matches_company("abatineva.com.tr", ["abatineva"])
    assert discovery._domain_matches_company(
        "abatineva.com.tr", discovery._company_tokens("Abatıneva")
    )


def test_native_provenance_terms_evidence_core_tokens():
    """Regression (found in the live TR run): folding only the TEXT side made
    "üretici" never match the folded page text, so "manufacturers" lost its
    Turkish evidence and every TR pallet maker dropped to icp_unconfirmed."""
    from opencold import icp_phrases

    profile = icp_phrases.parse_icp("pallet manufacturers")
    match = icp_phrases.evidence_core(
        profile, "Palet ÜRETİCİSİ firmamız", {"manufacturers": {"üretici"}, "pallet": {"palet"}}
    )
    assert match.confirmed
