from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from opencold import enricher
from opencold.discovery_contact_data import (
    _LINKEDIN_COMPANY_RE,
    _PHONE_RE,
    _SOCIAL_HOSTS,
    PARTNERSHIP_PATH_HINTS,
)
from opencold.discovery_contact_model import _CONTACT_PATHS, CompanyContacts
from opencold.discovery_data import (
    EMAIL_RE,
)
from opencold.discovery_domains import (
    normalize_domain,
)
from opencold.phones import normalize_phone as _clean_phone
from opencold.phones import region_hint


def _register_social(contacts: CompanyContacts, url: str) -> None:
    if not url or not isinstance(url, str):
        return
    low = url.lower()
    if "linkedin.com/company/" in low:
        match = _LINKEDIN_COMPANY_RE.search(url)
        clean = (match.group(0) if match else url).split("?")[0]
        if not contacts.linkedin_company_url:
            contacts.linkedin_company_url = clean
        if clean not in contacts.socials:
            contacts.socials.append(clean)
        return
    for host in _SOCIAL_HOSTS:
        if host in low:
            clean = url.split("?")[0]
            if clean not in contacts.socials:
                contacts.socials.append(clean)
            break


def _extract_jsonld_org(soup: BeautifulSoup) -> dict:
    """Pull contact fields from JSON-LD Organization/LocalBusiness blocks."""
    out = {"email": "", "telephone": "", "address": "", "sameAs": [], "name": ""}
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        flat = []
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                flat.extend(item["@graph"])
            else:
                flat.append(item)
        for item in flat:
            if not isinstance(item, dict):
                continue
            if not out["name"] and isinstance(item.get("name"), str):
                out["name"] = item["name"].strip()
            if not out["email"]:
                email = item.get("email", "")
                if isinstance(email, str) and "@" in email:
                    out["email"] = email.replace("mailto:", "").strip()
            if not out["telephone"]:
                tel = item.get("telephone", "")
                if isinstance(tel, str) and tel.strip():
                    out["telephone"] = tel.strip()
            same_as = item.get("sameAs", [])
            if isinstance(same_as, str):
                same_as = [same_as]
            if isinstance(same_as, list):
                out["sameAs"].extend([s for s in same_as if isinstance(s, str)])
            if not out["address"]:
                addr = item.get("address")
                if isinstance(addr, dict):
                    parts = [
                        str(addr.get(k, ""))
                        for k in (
                            "streetAddress",
                            "addressLocality",
                            "addressRegion",
                            "postalCode",
                            "addressCountry",
                        )
                    ]
                    out["address"] = ", ".join(p for p in parts if p and p != "None").strip(", ")
                elif isinstance(addr, str) and addr.strip():
                    out["address"] = addr.strip()
    return out


def extract_company_contacts(
    website: str, max_pages: int = 5, region_cc: str = ""
) -> CompanyContacts:
    """Extract a durable company contact bundle, structured-data first.

    Parses JSON-LD Organization/LocalBusiness (email/telephone/address/sameAs),
    mailto:/tel: anchors, and footer social links across a few high-value pages.
    Regex email/phone extraction is used only as a fallback when nothing
    structured is found.
    """
    contacts = CompanyContacts()
    base = enricher.normalize_url(website)
    if not base:
        return contacts
    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    domain = normalize_domain(website)
    seen_emails: set[str] = set()
    seen_phones: set[str] = set()
    home_text = ""
    hint = region_hint(website, region_cc)  # parse local numbers (05...) for this country

    for path in _CONTACT_PATHS[:max_pages]:
        url = origin if not path else urljoin(origin, path)
        html = enricher._fetch_html(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        if not path:
            home_text = soup.get_text(" ", strip=True)

        org = _extract_jsonld_org(soup)
        if org["name"] and not contacts.company_name:
            contacts.company_name = org["name"]
        if org["email"] and org["email"].lower() not in seen_emails:
            seen_emails.add(org["email"].lower())
            contacts.emails.append((org["email"].lower(), url))
        if org["telephone"]:
            tel = _clean_phone(org["telephone"], hint)
            if tel and tel not in seen_phones:
                seen_phones.add(tel)
                contacts.phones.append(tel)
        if org["address"] and not contacts.address:
            contacts.address = org["address"]
        for same in org["sameAs"]:
            _register_social(contacts, same)

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            low = href.lower()
            if low.startswith("mailto:"):
                email = href[7:].split("?")[0].strip().lower()
                if "@" in email and email not in seen_emails:
                    seen_emails.add(email)
                    contacts.emails.append((email, url))
            elif low.startswith("tel:"):
                tel = _clean_phone(href[4:], hint)
                if tel and tel not in seen_phones:
                    seen_phones.add(tel)
                    contacts.phones.append(tel)
            else:
                _register_social(contacts, urljoin(url, href))
                if not contacts.partnership_url and any(
                    f"/{hint}" in low or low.rstrip("/").endswith(hint)
                    for hint in PARTNERSHIP_PATH_HINTS
                ):
                    full = urljoin(url, href).split("#")[0]
                    if normalize_domain(full) == domain:
                        contacts.partnership_url = full

        # Regex email fallback only when nothing on-domain found yet.
        if not contacts.emails:
            for email in EMAIL_RE.findall(soup.get_text(" ", strip=True)):
                el = email.lower()
                if (
                    "@" in el
                    and normalize_domain(el.split("@", 1)[1]) == domain
                    and el not in seen_emails
                ):
                    seen_emails.add(el)
                    contacts.emails.append((el, url))

    # Phone regex fallback from the home page text. Weakest source, so require the
    # raw match to LOOK like a displayed phone: a "+" prefix or >=2 separator chars
    # ("05 22 77 71 00") — bare digit runs are usually IDs, years, or counters.
    if not contacts.phones and home_text:
        match = _PHONE_RE.search(home_text)
        if match:
            raw = match.group(1)
            formatted = raw.lstrip().startswith("+") or len(re.findall(r"[\s().\-]", raw)) >= 2
            tel = _clean_phone(raw, hint) if formatted else ""
            if tel:
                contacts.phones.append(tel)

    return contacts
