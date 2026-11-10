"""Known bugs, pinned as strict xfail tests (offline: synthetic HTML and mocks).

Each test asserts the CORRECT behaviour. Today it fails (XFAIL). When a fix lands
the test passes, strict=True turns that XPASS into a failure, and the xfail marker
must be removed so the test becomes a regular regression guard.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from opencold import discovery, smearch_enrich
from opencold.discovery import CompanyContacts, SearchResult
from opencold.enricher import PageContent


def known_bug(reason: str):
    return pytest.mark.xfail(strict=True, reason=reason)


def _contacts_from_home(html: str, website: str = "https://firma.com.tr") -> CompanyContacts:
    """extract_company_contacts with only the home page served (no network)."""
    home = website.rstrip("/")
    with patch(
        "opencold.discovery.enricher._fetch_html",
        side_effect=lambda url, *a, **k: html if url.rstrip("/") == home else None,
    ):
        return discovery.extract_company_contacts(website, max_pages=1)


# ── e-mail ───────────────────────────────────────────────────────────────────


@known_bug("reserved example.com placeholder from a site theme is picked as the contact email")
def test_example_com_email_is_not_the_contact():
    html = '<html><body><a href="mailto:consalti@example.com">Mail</a></body></html>'
    contacts = _contacts_from_home(html)
    email, _etype, _src = discovery.pick_company_email(contacts.emails, "firma.com.tr")
    assert email != "consalti@example.com"


@pytest.mark.parametrize(
    "address",
    [
        pytest.param("palet@firma.com.tr", marks=known_bug("palet@ typed as person_email")),
        pytest.param(
            "service-cooling@firma.com.tr",
            marks=known_bug("service-cooling@ typed as person_email"),
        ),
        "info@firma.com.tr",  # already correct today; kept as a regression guard
    ],
)
def test_role_inboxes_are_typed_role_inbox(address):
    _email, etype, _src = discovery.pick_company_email([(address, "u")], "firma.com.tr")
    assert etype == "role_inbox"


# ── phones ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("1779228338", marks=known_bug("unix timestamp accepted as a phone")),
        pytest.param("20261234", marks=known_bug("8-digit year-like run accepted as a phone")),
        pytest.param("012062058120341", marks=known_bug("15-digit ID accepted as a phone")),
    ],
)
def test_digit_runs_are_not_phones(raw):
    assert discovery._clean_phone(raw) == ""


@pytest.mark.parametrize(
    "local, e164",
    [
        pytest.param(
            "05333932020", "+905333932020", marks=known_bug("TR mobile kept in local format")
        ),
        pytest.param(
            "02169994998", "+902169994998", marks=known_bug("TR landline kept in local format")
        ),
    ],
)
def test_turkish_local_numbers_normalize_to_plus90_and_count_for_region(local, e164):
    contacts = _contacts_from_home(f'<html><body><a href="tel:{local}">Ara</a></body></html>')
    assert contacts.phones == [e164]
    _score, reasons = discovery.region_fit(contacts, "https://firma.com.tr", "Turkey")
    assert "phone:+90" in reasons


def test_control_plus90_phone_counts_for_region():
    """Control: the region signal works once the number is in +90 form."""
    contacts = CompanyContacts(phones=["+905333932020"])
    _score, reasons = discovery.region_fit(contacts, "https://firma.com", "Turkey")
    assert "phone:+90" in reasons


# ── region text (Turkish dotted capital İ) ───────────────────────────────────


def test_izmir_in_address_is_a_turkey_signal():
    contacts = CompanyContacts(address="Ulukent Sanayi Sitesi, Menemen / İZMİR")
    _score, reasons = discovery.region_fit(contacts, "https://firma.com", "Turkey")
    assert "addr_region_match" in reasons


def test_izmir_in_page_text_is_a_turkey_mention():
    _score, reasons = discovery.region_fit(
        CompanyContacts(), "https://firma.com", "Turkey", pages_text="Adres: Menemen / İZMİR"
    )
    assert "page_region_mention" in reasons


def test_control_ascii_izmir_in_address_is_a_turkey_signal():
    """Control: the same address in ASCII case matches, isolating the İ bug."""
    contacts = CompanyContacts(address="Ulukent Sanayi Sitesi, Menemen / Izmir")
    _score, reasons = discovery.region_fit(contacts, "https://firma.com", "Turkey")
    assert "addr_region_match" in reasons


# ── website resolution (smearch) ─────────────────────────────────────────────


@known_bug("UK (Warlingham) company gets a Danish namesake site (+45 phone, DK address)")
def test_uk_company_is_not_given_a_danish_site():
    row = {
        "company_name": "NORDIC PALLETS LTD",
        "company_number": "01234567",
        "address_line_1": "1 Westhall Road",
        "locality": "Warlingham",
        "postal_code": "CR6 9HB",
        "country": "United Kingdom",
    }
    danish = CompanyContacts(
        emails=[("info@nordicpallets.dk", "https://nordicpallets.dk")],
        phones=["+4575123456"],
        address="Industrivej 12, 7100 Vejle, Denmark",
    )
    page = PageContent(
        url="https://nordicpallets.dk",
        text="Nordic Pallets ApS, Industrivej 12, 7100 Vejle, Danmark. Tlf +45 75 12 34 56",
    )
    with (
        patch(
            "opencold.discovery.web_search",
            return_value=[
                SearchResult(title="Nordic Pallets", url="https://www.nordicpallets.dk/")
            ],
        ),
        patch("opencold.discovery.extract_company_contacts", return_value=danish),
        patch("opencold.discovery.crawl_company_pages", return_value=[page]),
        patch("opencold.smearch_enrich.ch.list_active_officers", return_value=[]),
    ):
        out = smearch_enrich.enrich_row(dict(row), ch_key="test-key")
    assert "nordicpallets.dk" not in out["website"]
