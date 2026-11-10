"""phones: validation + E.164 normalization, region hints, region signal."""

from opencold import discovery
from opencold.discovery import CompanyContacts
from opencold.phones import calling_code, iso_region, normalize_phone, region_hint


def test_iso_region_maps_cctlds():
    assert iso_region("tr") == "TR"
    assert iso_region("uk") == "GB"
    assert iso_region("com") is None


def test_region_hint_prefers_cctld_then_fallback():
    assert region_hint("https://firma.com.tr/iletisim") == "TR"
    assert region_hint("https://firma.com", "tr") == "TR"
    assert region_hint("https://firma.com") is None


def test_normalize_phone():
    assert normalize_phone("0533 393 20 20", "tr") == "+905333932020"
    assert normalize_phone("+90 (216) 999 49 98") == "+902169994998"
    assert normalize_phone("0533 393 20 20") == ""  # local, no country known
    assert normalize_phone("not a phone", "tr") == ""


def test_calling_code():
    assert calling_code("+905333932020") == "+90"
    assert calling_code("") == ""


def test_region_signal_uses_the_numbers_country_code_not_a_substring():
    # A Danish number containing "90" must not count as a Turkish phone.
    dk = CompanyContacts(phones=["+4590123456"])
    _score, reasons = discovery.region_fit(dk, "https://firma.com", "Turkey")
    assert "phone:+90" not in reasons
