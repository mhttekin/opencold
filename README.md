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

```
discover sources.txt --icp "developer tools" -o leads.csv
```

`sources.txt` is one URL per line — ecosystem pages, partner pages, directories, etc.
Finds companies, scores ICP fit, and discovers contacts via public emails and LinkedIn
search. Only includes verified emails; falls back to LinkedIn profile URLs when
verification fails. Filters out generic inboxes (`support@`, `contact@`, `info@`).

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
