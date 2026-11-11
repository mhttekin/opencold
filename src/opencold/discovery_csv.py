"""Company discovery CSV fields and review banner."""

COMPANY_CSV_FIELDS = [
    "email",
    "name",
    "company",
    "website",
    "match_confidence",
    "verification",
    "country",
    "region_fit",
    "company_email",
    "email_type",
    "phone",
    "address",
    "linkedin_company_url",
    "partnership_channel",
    "size_tier",
    "icp_score",
    "matched_terms",
    "website_status",
    "company_summary",
    "personalization_facts",
    "source_urls",
    "personalization_score",
    "discovery_channel",
    "discovery_source_url",
    "discovered_at",
    "lead_score",
    "lead_score_reasons",
    "quality_warnings",
]
COMPANY_PEOPLE_FIELDS = [
    "contact_name",
    "contact_role",
    "contact_linkedin",
    "contact_stale_warning",
]

# Banner drawn in the CSV between verified Top-N and the review pile below.
WALL_BANNER = "═════ REVIEW BELOW — ICP/region NOT verified ═════"
