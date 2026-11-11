"""Source-grounded company and contact discovery."""

from __future__ import annotations

import csv  # noqa: F401
import json  # noqa: F401
import os  # noqa: F401
import re  # noqa: F401
import time  # noqa: F401
import urllib.request  # noqa: F401
from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from itertools import zip_longest  # noqa: F401
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse  # noqa: F401

from bs4 import BeautifulSoup  # noqa: F401

from opencold import discovery_reacher, enricher, icp_phrases, translator  # noqa: F401
from opencold import regions_data as rd  # noqa: F401
from opencold.discovery_candidates import _resolve_names, discover_company_candidates  # noqa: F401
from opencold.discovery_classify import _classify_company  # noqa: F401
from opencold.discovery_company_csv import write_company_csv  # noqa: F401
from opencold.discovery_company_linkedin import _linkedin_slug_matches, find_company_linkedin  # noqa: F401
from opencold.discovery_company_pipeline import discover_company_rows  # noqa: F401
from opencold.discovery_company_row import _now_iso, _score_company_lead, build_company_row  # noqa: F401
from opencold.discovery_contact_data import (
    _LINKEDIN_COMPANY_RE,  # noqa: F401
    _PHONE_RE,  # noqa: F401
    _SOCIAL_HOSTS,  # noqa: F401
    PARTNERSHIP_PATH_HINTS,  # noqa: F401
)
from opencold.discovery_contact_data import (
    COMPANY_EMAIL_PRIORITY as COMPANY_EMAIL_PRIORITY,
)
from opencold.discovery_contact_model import _CONTACT_PATHS, CompanyContacts  # noqa: F401
from opencold.discovery_contacts import (
    _extract_jsonld_org,  # noqa: F401
    _register_social,  # noqa: F401
    extract_company_contacts,  # noqa: F401
)
from opencold.discovery_country import _detect_phone_country, _detected_country  # noqa: F401
from opencold.discovery_csv import COMPANY_CSV_FIELDS, COMPANY_PEOPLE_FIELDS, WALL_BANNER  # noqa: F401
from opencold.discovery_data import (
    _COMPANY_NAME_PAT as _COMPANY_NAME_PAT,
)
from opencold.discovery_data import (
    _EMPLOYMENT_DATE_RE,  # noqa: F401
    _LINKEDIN_MAX_QUERIES,  # noqa: F401
    _LINKEDIN_QUERY_DELAY,  # noqa: F401
    _MOVED_PATTERNS,  # noqa: F401
    _NOT_EMPLOYED_RE,  # noqa: F401
    _SEARXNG_INSTANCES,  # noqa: F401
    _VERIFY_EMPLOYMENT,  # noqa: F401
    B2B_SIGNAL_RE,  # noqa: F401
    BAD_PERSON_WORDS,  # noqa: F401
    COMPANY_SUFFIXES_RE,  # noqa: F401
    CTA_TEXT,  # noqa: F401
    DISCOVERY_PATHS,  # noqa: F401
    EMAIL_RE,  # noqa: F401
    EXEC_ROLE_RE,  # noqa: F401
    GUESSED_ROLE_EMAILS,  # noqa: F401
    HIGH_VALUE_ROLE_PREFIXES,  # noqa: F401
    INTERNAL_DETAIL_HINTS,  # noqa: F401
    INTERNAL_SKIP_PARTS,  # noqa: F401
    LINKEDIN_SEARCH_QUERIES,  # noqa: F401
    LINKEDIN_TARGET_ROLES_RE,  # noqa: F401
    LINKEDIN_TITLE_RE,  # noqa: F401
    LOW_VALUE_ROLE_PREFIXES,  # noqa: F401
    NOISY_PRODUCT_RE,  # noqa: F401
    OUTREACH_USELESS_PREFIXES,  # noqa: F401
    PERSON_HINT_RE,  # noqa: F401
    PERSON_LOCAL_RE,  # noqa: F401
    PERSON_REVERSE_HINT_RE,  # noqa: F401
    RELEVANT_ROLE_RE,  # noqa: F401
    ROLE_PREFIXES,  # noqa: F401
    SEARCH_FETCH_MULTIPLIER,  # noqa: F401
    SEARCH_PAGE_LIMIT,  # noqa: F401
    SEARCH_PATH_HINTS,  # noqa: F401
    SEARCH_QUERIES,  # noqa: F401
    SEARCH_RESULT_LIMIT,  # noqa: F401
    SEARCH_TIMEOUT,  # noqa: F401
)
from opencold.discovery_data import BLOCKED_DOMAINS as BLOCKED_DOMAINS
from opencold.discovery_data import BLOCKED_HOST_PARTS as BLOCKED_HOST_PARTS
from opencold.discovery_data import SPACE_RE as SPACE_RE
from opencold.discovery_domains import (
    _AGGREGATOR_DOMAINS as _AGGREGATOR_DOMAINS,
)
from opencold.discovery_domains import (
    _AGGREGATOR_RE as _AGGREGATOR_RE,
)
from opencold.discovery_domains import (
    _AGGREGATOR_STEMS as _AGGREGATOR_STEMS,
)
from opencold.discovery_domains import (
    _SECOND_LEVEL_TLDS as _SECOND_LEVEL_TLDS,
)
from opencold.discovery_domains import (
    _clean_text as _clean_text,
)
from opencold.discovery_domains import (
    _company_from_anchor as _company_from_anchor,
)
from opencold.discovery_domains import (
    _company_from_domain as _company_from_domain,
)
from opencold.discovery_domains import (
    _is_aggregator as _is_aggregator,
)
from opencold.discovery_domains import (
    _is_blocked_domain as _is_blocked_domain,
)
from opencold.discovery_domains import (
    _is_blocked_host as _is_blocked_host,
)
from opencold.discovery_domains import (
    _is_government_domain as _is_government_domain,
)
from opencold.discovery_domains import (
    _registrable_domain as _registrable_domain,
)
from opencold.discovery_domains import (
    normalize_domain as normalize_domain,
)
from opencold.discovery_employment import verify_current_employment  # noqa: F401
from opencold.discovery_employment_parse import (
    _COMMON_ROLES_RE,  # noqa: F401
    _analyze_engine_results,  # noqa: F401
    _check_employment_dates,  # noqa: F401
    _company_in_title,  # noqa: F401
    _extract_linkedin_company_from_title,  # noqa: F401
    _parse_linkedin_title,  # noqa: F401
)
from opencold.discovery_icp_score import _icp_evidence, _icp_match, _icp_terms, score_company  # noqa: F401
from opencold.discovery_judge import (
    _JUDGE_SYSTEM,  # noqa: F401
    _build_judge_prompt,  # noqa: F401
    _country_matches,  # noqa: F401
    judge_companies,  # noqa: F401
)
from opencold.discovery_lead_score import _bad_company_name, score_lead  # noqa: F401
from opencold.discovery_linkedin import search_linkedin_contacts  # noqa: F401
from opencold.discovery_linkedin_parse import parse_linkedin_result_titles  # noqa: F401
from opencold.discovery_models import CandidateCompany, Contact  # noqa: F401
from opencold.discovery_page_search import (
    _merge_pages,  # noqa: F401
    _search_result_allowed,  # noqa: F401
    search_company_page_urls,  # noqa: F401
    search_company_pages,  # noqa: F401
)
from opencold.discovery_pages import crawl_company_pages  # noqa: F401
from opencold.discovery_people import discover_rows, write_csv  # noqa: F401
from opencold.discovery_person_contact import find_contact  # noqa: F401
from opencold.discovery_person_match import (
    _company_name_matches,  # noqa: F401
    _is_name_company_coincidence,  # noqa: F401
)
from opencold.discovery_person_score import (
    _email_rank,  # noqa: F401
    _has_contact_page,  # noqa: F401
    _name_from_email,  # noqa: F401
    _person_from_text,  # noqa: F401
    _valid_person_name,  # noqa: F401
    score_contact,  # noqa: F401
)
from opencold.discovery_query import (
    _candidate_from_result,  # noqa: F401
    _interleave_translations,  # noqa: F401
    discover_companies_by_query,  # noqa: F401
    region_query_templates,  # noqa: F401
)
from opencold.discovery_region import (
    _HQ_ADJ_RE,  # noqa: F401
    _HQ_CUSTOMER_RE,  # noqa: F401
    _HQ_PLACE,  # noqa: F401
    _HQ_VERB_RE,  # noqa: F401
    MAX_SEARCH_LANGS,  # noqa: F401
    _detect_address_country,  # noqa: F401
    _detect_domain_country,  # noqa: F401
    _detect_prose_location,  # noqa: F401
    _region_language,  # noqa: F401
    _region_languages,  # noqa: F401
    _resolve_place,  # noqa: F401
    _resolve_region_key,  # noqa: F401
    _target_region_tokens,  # noqa: F401
)
from opencold.discovery_region_data import (
    _AMBIGUOUS as _AMBIGUOUS,
)
from opencold.discovery_region_data import (
    _COUNTRY_DEMONYMS as _COUNTRY_DEMONYMS,
)
from opencold.discovery_region_data import (
    _COUNTRY_DEMONYMS_BY_LEN as _COUNTRY_DEMONYMS_BY_LEN,
)
from opencold.discovery_region_data import (
    _COUNTRY_NAMES as _COUNTRY_NAMES,
)
from opencold.discovery_region_data import (
    _COUNTRY_NAMES_BY_LEN as _COUNTRY_NAMES_BY_LEN,
)
from opencold.discovery_region_data import (
    _PHONE_CC as _PHONE_CC,
)
from opencold.discovery_region_data import (
    _REGION_ALIASES as _REGION_ALIASES,
)
from opencold.discovery_region_data import (
    _REGION_CCTLD as _REGION_CCTLD,
)
from opencold.discovery_region_data import (
    _REGION_CITIES as _REGION_CITIES,
)
from opencold.discovery_region_data import (
    _REGION_LANGS as _REGION_LANGS,
)
from opencold.discovery_region_data import (
    _REGION_PHONE as _REGION_PHONE,
)
from opencold.discovery_region_data import (
    _build_phone_cc as _build_phone_cc,
)
from opencold.discovery_region_fit import region_fit  # noqa: F401
from opencold.discovery_search import web_search  # noqa: F401
from opencold.discovery_search_fallback import _ddg_html_search, _mojeek_search, _searxng_search  # noqa: F401
from opencold.discovery_search_html import _duckduckgo_search_urls, _fetch_search_html  # noqa: F401
from opencold.discovery_search_models import SearchResult  # noqa: F401
from opencold.discovery_search_parse import _unwrap_duckduckgo_url, parse_search_result_urls  # noqa: F401
from opencold.discovery_search_primary import (
    _brave_search,  # noqa: F401
    _ddgs_search,  # noqa: F401
    _get_serper_key,  # noqa: F401
    _serper_search,  # noqa: F401
)
from opencold.discovery_seed import (
    _SEED_SYSTEM,  # noqa: F401
    _build_seed_prompt,  # noqa: F401
    _parse_json_object,  # noqa: F401
    _resolve_llm_provider,  # noqa: F401
    seed_companies_via_llm,  # noqa: F401
)
from opencold.discovery_size import size_tier  # noqa: F401
from opencold.discovery_size_data import _SIZE_BAND_RE, _SME_HINT_RE  # noqa: F401
from opencold.discovery_sources import (
    _PROJECT_ROOT,  # noqa: F401
    _clamp_workers,  # noqa: F401
    _fetch_source,  # noqa: F401
    _internal_detail_links,  # noqa: F401
    discover_companies,  # noqa: F401
    discover_company_pool,  # noqa: F401
    discover_from_source,  # noqa: F401
    extract_companies_from_html,  # noqa: F401
    load_sources,  # noqa: F401
)
from opencold.discovery_translation import (
    _NATIVE_FUNCTION_WORDS,  # noqa: F401
    _localize_enrichment,  # noqa: F401
    _translate_expansion_terms,  # noqa: F401
    _translate_icp_terms,  # noqa: F401
    _translate_one,  # noqa: F401
    _translate_profile,  # noqa: F401
    _translate_terms,  # noqa: F401
    _translated_term_ok,  # noqa: F401
)
from opencold.discovery_website import (
    WEBSITE_DIRECTORY_DOMAINS as WEBSITE_DIRECTORY_DOMAINS,
)
from opencold.discovery_website import (
    _company_tokens,  # noqa: F401
    _domain_matches_company,  # noqa: F401
    _is_directory_domain,  # noqa: F401
    resolve_company_website,  # noqa: F401
)
from opencold.discovery_wiki import (
    wikipedia_category_members,  # noqa: F401
    wikipedia_company_names,  # noqa: F401
    wikipedia_list_titles,  # noqa: F401
)
from opencold.discovery_wiki_parse import (
    _WIKI_NAME_BLOCKLIST_RE,  # noqa: F401
    _WIKI_SKIP_SECTIONS,  # noqa: F401
    _WIKI_UA,  # noqa: F401
    WIKIPEDIA_API,  # noqa: F401
    _clean_wiki_name,  # noqa: F401
    _parse_wikitext_names,  # noqa: F401
    _wiki_api_get,  # noqa: F401
    _wikitable_first_cells,  # noqa: F401
)
from opencold.emails import pick_company_email  # noqa: F401

# Re-exported names: tests and icp_expansion resolve these via opencold.discovery.
from opencold.icp_phrases import GENERIC_ICP_TERMS  # noqa: F401
from opencold.icp_phrases import stem as _stem  # noqa: F401
from opencold.phones import calling_code, region_hint  # noqa: F401
from opencold.phones import normalize_phone as _clean_phone  # noqa: F401
from opencold.textnorm import fold  # noqa: F401

# Re-export the Reacher helpers and constants from their owner.
_REACHER_VERSION = discovery_reacher._REACHER_VERSION
_REACHER_BIN_DIR = discovery_reacher._REACHER_BIN_DIR
_REACHER_BIN_NAME = discovery_reacher._REACHER_BIN_NAME
_reacher_target_triple = discovery_reacher._reacher_target_triple
_download_reacher = discovery_reacher._download_reacher
_find_reacher_binary = discovery_reacher._find_reacher_binary
_reacher_check = discovery_reacher._reacher_check
_generate_email_patterns = discovery_reacher._generate_email_patterns
_guess_email_from_name = discovery_reacher._guess_email_from_name


def __getattr__(name: str) -> str | None | bool:
    # The owner rebinds the cache as it resolves the binary. Expose its current value.
    if name == "_REACHER_BIN":
        return discovery_reacher._REACHER_BIN
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
