"""Offline characterization of the discovery runtime after split unit 01-data.

The snapshot contains every returned field, including internal verification flags,
and preserves ranked row order. Regeneration requires Mehmet's approval. Only
external inputs and the clock are replaced; discovery, crawling, HTML extraction,
website resolution, translation orchestration, scoring and classification run.
"""

import json
import time
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import urlparse

from opencold import discovery, enricher, translator

GOLDEN = Path(__file__).parent / "fixtures" / "discover_golden.json"
FROZEN_TIME = time.struct_time((2026, 11, 10, 0, 0, 0, 1, 314, 0))
WIKI_SOURCE = "https://en.wikipedia.org/wiki/List_of_pallet_companies_in_France"


def _page(title, description, body=""):
    return (
        f'<html><head><title>{title}</title><meta name="description" '
        f'content="{description}"></head><body><h1>{title}</h1>{body}</body></html>'
    )


# Ten companies: nine with search results, plus Invisible with no resolvable site.
# Hollow has a domain but no fetchable pages. Input order deliberately differs
# from output rank, so sorting regressions change the snapshot.
SITES = {
    "hollow.fr": None,
    "eclat.com": _page(
        "Eclat",
        "Eclat builds wooden pallets for industrial shipping and storage worldwide.",
    ),
    "guide.fr": _page(
        "Guide",
        "Guide connects buyers and suppliers in a business directory of pallets.",
        '<a href="mailto:sales@guide.fr">Email sales</a>',
    ),
    "fjord.de": _page(
        "Fjord",
        "Fjord manufactures wooden pallets for industrial transport and storage.",
        '<a href="mailto:info@fjord.de">Contact</a>',
    ),
    "durable.fr": _page(
        "Durable",
        "Nous fabriquons des palettes durables pour le transport de marchandises.",
        "<p>Une entreprise familiale de 8 employees.</p>",
    ),
    "cedre.com": _page(
        "Cedre",
        "Cedre provides wooden pallets for warehouses and industrial customers.",
        '<script type="application/ld+json">'
        '{"@type":"Organization","name":"Cedre","address":'
        '{"streetAddress":"12 Rue du Port","addressLocality":"Lyon",'
        '"postalCode":"69002","addressCountry":"France"}}</script>'
        "<p>Our growing business has 250 employees.</p>",
    ),
    "boreal.com": _page(
        "Boreal",
        "Boreal offers wooden pallets and reliable deliveries for warehouse teams.",
        '<a href="mailto:partnerships@boreal.com">Partnerships</a>'
        '<a href="tel:+33142345678">Telephone</a>'
        "<p>Our production team includes 45 employees.</p>",
    ),
    "iris.fr": _page(
        "Iris",
        "Nous produisons des supports en bois pour transporter les marchandises.",
    ),
    "atlas.fr": _page(
        "Atlas Pallets",
        "Atlas builds wooden pallets and offers custom logistics support for exporters.",
        '<script type="application/ld+json">'
        '{"@type":"Organization","name":"Atlas Pallets",'
        '"email":"partnerships@atlas.fr","telephone":"+33144556677",'
        '"address":{"streetAddress":"8 Rue des Ateliers","addressLocality":"Paris",'
        '"postalCode":"75010","addressCountry":"France"},'
        '"sameAs":["https://www.linkedin.com/company/atlas-pallets/"]}</script>'
        '<a href="/partnerships">Partner with us</a>'
        "<p>Our production network has 1200 employees.</p>",
    ),
}
EXTRA_PAGES = {
    "https://atlas.fr/team": _page(
        "Atlas Team",
        "Our engineering team supports warehouse automation and industrial customers.",
        "<p>Founder: Ada Lovelace</p>",
    ),
    "https://atlas.fr/contact": _page(
        "Contact Atlas",
        "Atlas provides direct access to our team for custom wooden pallet projects.",
        '<a href="mailto:ada.lovelace@atlas.fr">Ada Lovelace</a>',
    ),
}
IRIS_ENGLISH = "We manufacture wooden pallets for transporting industrial goods."


def _offline_rows(monkeypatch):
    """Wire fixture transports; never replace candidate building or row logic."""

    def fetch(url, timeout=enricher.FETCH_TIMEOUT):
        parsed = urlparse(url)
        if parsed.path.rstrip("/") == "":
            return SITES.get(parsed.netloc)
        return EXTRA_PAGES.get(url)

    def search(query, num=10):
        if "site:linkedin.com" in query:
            return []
        if "site:" in query or '"atlas.fr"' in query:
            if "atlas.fr" in query:
                return [discovery.SearchResult("Atlas team", "https://atlas.fr/team")]
            return []
        if "official website" in query or query.startswith('"'):
            if "Invisible" in query:
                # A directory listing is not an official company website.
                return [discovery.SearchResult("Invisible", "https://crunchbase.com/org/invisible")]
            if "Atlas Pallets" in query:
                return [discovery.SearchResult("Atlas Pallets", "https://atlas.fr")]
            return []
        return [
            *(discovery.SearchResult(domain, f"https://{domain}") for domain in SITES),
            discovery.SearchResult("Atlas duplicate", "https://www.atlas.fr/about"),
            discovery.SearchResult("Directory listing", "https://crunchbase.com/org/atlas"),
        ][:num]

    def translate(text, target, source="auto"):
        if target == "fr":
            return text.replace("pallets", "palettes")
        if target == "en" and source == "fr":
            return text.replace("palettes", "pallets")
        if target == "en" and "Nous produisons des supports" in text:
            return IRIS_ENGLISH
        return text

    search_mock = Mock(side_effect=search)
    translate_mock = Mock(side_effect=translate)
    wiki_mock = Mock(return_value=[("Atlas Pallets", WIKI_SOURCE), ("Invisible", WIKI_SOURCE)])
    monkeypatch.setattr(discovery, "web_search", search_mock)
    monkeypatch.setattr(discovery, "wikipedia_company_names", wiki_mock)
    monkeypatch.setattr(enricher, "_fetch_html", fetch)
    monkeypatch.setattr(translator, "translate", translate_mock)
    # Freeze the input clock, without replacing the discovery timestamp helper.
    monkeypatch.setattr(discovery.time, "gmtime", lambda: FROZEN_TIME)
    rows = discovery.discover_company_rows(
        "pallets", "France", limit=10, workers=1, max_pages=3, use_expansion=False
    )
    wiki_mock.assert_called_once_with("pallets", "France", max_names=30)
    assert any("Invisible" in c.args[0] for c in search_mock.call_args_list)
    assert any("palettes" in c.args[0] for c in search_mock.call_args_list)
    assert any(c.args[1] == "en" for c in translate_mock.call_args_list)
    return rows


def test_discover_company_rows_golden(monkeypatch, tmp_config):
    # tmp_config leaves provider resolution real, with an empty isolated config.
    assert discovery._resolve_llm_provider() is None
    rows = _offline_rows(monkeypatch)
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert rows == expected
    assert [list(row) for row in rows] == [list(row) for row in expected]
