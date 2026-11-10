# Architecture

Product focus: company research and enrichment (`discover`, `smearch`, `prepare`).
Email drafting/sending code (`generator`, `prompts`, `sender`, `run`/`draft`/`send`)
is legacy and not documented in the README.

## CLI (`cli.py`)
Typer app plus a prompt_toolkit REPL. Each command has a `do_<cmd>()` implementation
called by both the Typer command and the REPL; the REPL parses its own tokens via
`_parse_<cmd>_args()`. When adding or changing a flag, update all three: the Typer
signature, the `_parse_*_args` parser, and the REPL help text.

## `discover` (companies mode) — `discovery.py`
The largest module. Pipeline in `discover_company_rows()`:
1. **ICP understanding**: `icp_phrases` chunks the ICP into phrases (multi-word ICPs
   require all core tokens; no single-word verification). `icp_expansion` +
   `icp_synonyms` add related terms (keyless lexicon + Datamuse, optional LLM),
   half-weighted. Disabled with `--no-expand`.
2. **Candidate channels**, merged in `discover_company_candidates()`: LLM seeding
   (`seed_companies_via_llm`, skipped with no provider / `--no-llm`), Wikipedia
   "List of …" harvest (`--no-wiki`), search harvest (`discover_companies_by_query`)
   including native-language queries interleaved with English via `translator`
   (keyless Lingva; `--no-translate`), optional sources file.
3. **Website resolution**: `resolve_company_website()`. Watch public-suffix handling
   (`_registrable_domain`) and name↔domain matching, which are known sources of
   wrong-company attachment.
4. **Per-company enrichment**: crawl pages, `extract_company_contacts()` (emails,
   phones, JSON-LD, socials), `pick_company_email`, `find_company_linkedin`,
   `region_fit`, `size_tier`.
5. **Verification**: deterministic ICP evidence (`_icp_evidence`; translated terms
   filtered against function words/round-trip, ≥2 weak hits needed) and region
   signals (ccTLD, phone code, address), plus an optional batched grounded LLM judge
   (`judge_companies`). The LLM owns industry judgement; deterministic signals own
   region; LLM `unknown` defers to deterministic and never rejects.
   `_classify_company` yields `match_confidence` verified/review/rejected.
6. **Output**: `write_company_csv` writes verified rows first, then a `REVIEW BELOW`
   banner and the rest.

`web_search()` is a fallback chain across engines (Serper if `SERPER_API_KEY`, ddgs,
Brave, Mojeek, SearXNG, DDG HTML). Region data lives in `regions_data.py`.

## `smearch`: UK SMEs via Companies House
`sic_match` maps ICP → SIC codes (`sic_data`, `sic_categories`). `smearch` queries
`companies_house` and scores/ranks results (account type, officers, recency,
dormancy). `smearch_enrich` enriches the top N by reusing `discovery`'s search/contact
stack, with `google_places` as a fallback when no website is found.
`smearch_db` keeps a SQLite seen-set of output company numbers (`~/.opencold/smearch.db`,
override with `OPENCOLD_SMEARCH_DB`) so repeat runs skip them and page on; `--no-db` disables it.

SIC candidates come from two offline sources, merged per code in `sic_match`:
SIC-title term overlap, plus BM25 (`sic_index`) over the ONS alphabetical index
(`sic_index_data.csv`, ~16k activity phrases → SIC 2007 code). Ranking weights
(role bonus, `BM25_WEIGHT`) and the low-confidence gate (`SIC_CONFIDENCE_MIN`:
below it smearch shows the top-5 and asks for `--sic`) live in `sic_rank`.
Hybrid (BM25 + embedding) retrieval was tried and not adopted for now: see
`docs/decisions/0001-sic-hybrid-retrieval.md`.

The index data is built by `scripts/build_sic_index.py` from the Office for National
Statistics workbook "UK SIC 2007 Indexes with addendum December 2022 reformatted
September 2024"
(https://www.ons.gov.uk/methodology/classificationsandstandards/ukstandardindustrialclassificationofeconomicactivities/uksic2007).
Source: Office for National Statistics, licensed under the Open Government Licence v3.0
(https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Contains public sector information licensed under the Open Government Licence v3.0.

## `prepare` / `pipeline.py`
`pipeline.py` is the headless pipeline used by the CLI and designed to be embedded in
an API (a FastAPI wrapper is archived on branch `archive/server-web`). No disk
config, prompts, printing, or file writes: inputs come in resolved, progress goes out
via a callback of plain dicts (never secrets). `enricher` crawls sites and scores
facts; `crawler` extracts descriptions; `verifier` checks emails (optional Reacher
binary auto-downloaded into `vendor/bin`); `quality` produces review warnings.

## Config
`config.py` stores everything in `~/.opencold/config.json` (identity, profiles,
providers incl. `serper`/`companies_house`/`google_places` keys) and loads a
repo-root `.env` without overriding existing env vars. Tests must use the
`tmp_config` / `seeded_config` fixtures in `tests/conftest.py`, which redirect
`CONFIG_DIR`/`CONFIG_FILE`.

LLM tiers (seeding, judge, expansion) must stay provider-pluggable and degrade to
keyless/deterministic behavior when no provider is configured. Callers may inject
their own model.
