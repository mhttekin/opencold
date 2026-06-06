# OpenCold

CLI tool for personalized cold outreach emails powered by LLMs. Discovers leads, enriches them with website data, generates personalized emails, and sends via SMTP.

## Install

```bash
pip install -e .
pip install -e ".[dev]"  # with dev/test deps
```

## Quick Start

```bash
opencold          # launches interactive shell
config init       # first-time setup: identity, API key, profile
```

## Workflow

```
# Full pipeline — from raw leads to sent emails
run leads.csv --send

# Or step by step
prepare leads.csv -o enriched.csv    # enrich with website facts
review enriched.csv                  # check warnings
draft enriched.csv -o drafts.csv     # generate emails
review drafts.csv                    # check drafts
send drafts.csv                      # send via SMTP
```

Input CSV needs: `email`, `first_name`, `last_name`, `company`, and optionally `website`.

## Discover Leads (Experimental)

> Discovery relies on web scraping and search engines which may fail due to rate
> limits or CAPTCHAs. Can take several minutes. Always review results before outreach.

### Companies mode (default)

Give an ideal customer profile and a region; OpenCold builds a ranked **company
list** with a durable contact bundle — company email (partnership/BD inbox
preferred), phone, address, and the **company** LinkedIn page — plus a region-fit
score and a coarse size tier.

```
discover --icp "insurance companies" --region "Bangladesh" -o leads.csv
```

Candidate companies are discovered at runtime (no curated source file needed):

- **LLM seeding** — if an LLM provider is configured, Claude names known companies
  for the (ICP, region) and points at authoritative local indexes (regulators,
  associations). Skipped automatically when no provider is set up.
- **Wikipedia lists** — harvests company names from "List of …" pages when one
  exists. Deterministic, no LLM.
- **Search harvest** — region + ICP queries through the search stack, with
  directories/aggregators filtered out.
- **Sources file** *(optional)* — pass a `sources.txt` as an extra channel.

Output columns include `company`, `website`, `company_email`, `email_type`,
`phone`, `address`, `linkedin_company_url`, `partnership_channel`, `region_fit`,
and `size_tier`. Rows without an email are kept (still useful via phone/LinkedIn);
use `--require-contact` to drop them.

**Verification & the wall.** Each lead is checked against the ICP and region using
the company's own crawled content (not just its name), so wrong-industry / wrong-country
namesakes don't slip in. Two signals drive a `match_confidence` (verified / review /
rejected) and a `verification` reason:

- Deterministic: ICP terms present in the crawled text; ccTLD / phone code / city for region.
- LLM judge (only if a provider is configured): one batched call reads the crawled
  summaries and rules each company match `yes/no/unknown`, grounded in a quoted phrase.
  It owns *industry* judgement; deterministic signals own *region* (hard facts). When the
  model is unsure (`unknown`) it defers to the deterministic check — it never rejects on
  ignorance. With no provider, discovery runs deterministic-only.

The CSV lists **verified** leads first (your real Top-N), then a blank gap and a
`REVIEW BELOW` banner, then the review/rejected pile so you can scan and salvage.

Add `--find-people` to also search a named contact per company. **Note:** person→
company mappings come from public search and can be stale — verify before outreach.

### People mode (legacy)

```
discover sources.txt --mode people --icp "developer tools" -o leads.csv
```

`sources.txt` is one URL per line — ecosystem pages, partner pages, directories.
Finds a contact per company via public emails and LinkedIn search.

## SMTP

```
smtp setup   # interactive config
smtp test    # verify connection
smtp show    # show saved config
```

## Commands

| Command | Description |
|---------|-------------|
| `run <csv>` | Prepare + draft (+ send with `--send`) |
| `prepare <csv>` | Enrich leads with website facts |
| `draft <csv>` | Generate emails from enriched leads |
| `discover <sources>` | Find leads from public source pages |
| `review <csv>` | Print enrichment/draft warnings |
| `send <csv>` | Send generated emails via SMTP |
| `profile list/create/use/delete` | Manage sender identities |
| `provider list/add/delete/default` | Manage LLM providers |

Use `--help` on any command for full options.

## Tests

```bash
pytest
```
