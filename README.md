# OpenCold

CLI for company research. Finds companies that match an ideal customer profile (ICP) and enriches them with website facts and contact details.

## Install

```bash
pip install -e .
pip install -e ".[dev]"  # with dev/test deps
```

## Quick Start

```bash
opencold          # launches interactive shell
config init       # first-time setup
```

An LLM provider is optional. Without one, research runs deterministic-only.

## Discover Companies (Experimental)

> Relies on web scraping and search engines, which may hit rate limits or CAPTCHAs.
> Can take several minutes. Always review results.

```
discover --icp "insurance companies" --region "Bangladesh" -o leads.csv
```

Builds a ranked company list from LLM seeding, Wikipedia lists, and web search (including local-language search). Each company's own site is crawled and checked against the ICP and region.

Output includes `company`, `website`, `company_email`, `phone`, `address`, `linkedin_company_url`, `region_fit`, `size_tier`, and `match_confidence`. Verified companies come first, followed by a `REVIEW BELOW` section.

Useful flags: `--limit`, `--require-contact`, `--find-people`, `--no-llm`, `--no-wiki`, `--no-translate`, `--no-expand`.

## UK SMEs via Companies House (Experimental)

```
smearch "timber merchants" --location London -o smes.csv
```

Matches the ICP to SIC codes, queries Companies House, ranks the results, and enriches the top N with website, contacts, and officers. Requires `COMPANIES_HOUSE_API_KEY`.

Useful flags: `--sic`, `--role`, `--size`, `--top-n`, `--no-enrich`, `--dry-run`.

## Enrich an Existing List

Input CSV needs `company` and, ideally, `website`.

```
prepare companies.csv -o enriched.csv   # add website facts
review enriched.csv                     # check warnings
verify enriched.csv                     # verify email addresses
```

## Commands

| Command | Description |
|---------|-------------|
| `discover` | Find companies by ICP + region |
| `smearch <icp>` | Find UK SMEs via Companies House |
| `prepare <csv>` | Enrich companies with website facts |
| `review <csv>` | Print enrichment warnings |
| `verify <csv>` | Verify email addresses |
| `provider list/add/delete/default` | Manage LLM providers |

Use `--help` on any command for full options.

## Tests

```bash
pytest
```
