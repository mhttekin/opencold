"""emails: placeholder rejection and person-vs-role by known names."""

import pytest

from opencold.emails import is_placeholder_email, local_matches_name, pick_company_email


@pytest.mark.parametrize(
    "email",
    ["a@example.com", "a@mail.example.net", "a@shop.test", "a@x.invalid", "a@site.example"],
)
def test_reserved_domains_are_placeholders(email):
    assert is_placeholder_email(email)


def test_real_addresses_are_not_placeholders():
    assert not is_placeholder_email("info@sahinlerpalet.com.tr")


@pytest.mark.parametrize(
    "local, names",
    [
        ("jane.smith", ["Jane Smith"]),
        ("jsmith", ["Jane Smith"]),
        ("smith", ["SMITH, Jane Mary"]),  # Companies House officer format
        ("hasan", ["Hasan Silah"]),
        ("ozlem", ["Özlem Kaya"]),  # folded: ö -> o
    ],
)
def test_local_matches_known_name(local, names):
    assert local_matches_name(local, names)


@pytest.mark.parametrize("local", ["palet", "info", "service-cooling", "jo"])
def test_local_without_a_known_name_is_not_a_person(local):
    assert not local_matches_name(local, ["Jane Smith", "Jo Li"])


def test_officer_name_makes_a_person_email():
    emails = [("info@acme-widgets.co.uk", "u"), ("jsmith@acme-widgets.co.uk", "u")]
    picked = pick_company_email(emails, "acme-widgets.co.uk", ["SMITH, Jane"])
    assert picked[:2] == ("jsmith@acme-widgets.co.uk", "person_email")
