# Discovery split implementation plan

Goal: pure extraction of discovery.py into modules below 400 lines, preserving
public names, signatures, return values, ordering, fallbacks and side effects.
No source moves in the initializer. `features.json` is the ordered work queue.

## Target module map and dependency direction

All paths below are under `src/opencold/`. Each row is one session/unit in queue
order. Line spans refer to initializer commit `5ef9330` and are navigation aids;
use the symbol lists in features.json after earlier moves change line numbers.
Associated constants, classes and comments move with their owner; the description
lists every owned top-level symbol, including definitions whose functions list is
empty. Existing external imports are retained only where used.

Imports point from each row to its listed prerequisites (all earlier rows), never
back to discovery.py. The facade imports/re-exports all original names, including
private helpers and imported aliases used externally. No wildcard imports.
No child module imports the facade, even lazily. This graph is topologically
sorted from AST name references; inspect dynamic/local imports at each move too.

| Unit | Target module | Original span | Prerequisites (discovery_ prefix omitted) |
|---|---|---|---|
| 01-data | `discovery_data.py` | 35–390 | none |
| 02-models | `discovery_models.py` | 391–408 | none |
| 03-search_models | `discovery_search_models.py` | 726–735 | none |
| 04-reacher | `discovery_reacher.py` | 1345–1510 | none |
| 05-contact_data | `discovery_contact_data.py` | 2792–2847 | none |
| 06-region_data | `discovery_region_data.py` | 2848–2884 | none |
| 07-size_data | `discovery_size_data.py` | 3024–3037 | none |
| 08-seed | `discovery_seed.py` | 3038–3156 | none |
| 09-contact_model | `discovery_contact_model.py` | 3635–3656 | none |
| 10-csv | `discovery_csv.py` | 4133–4173 | none |
| 11-domains | `discovery_domains.py` | 409–536 | data |
| 12-pages | `discovery_pages.py` | 692–707 | data |
| 13-search_html | `discovery_search_html.py` | 708–725 | data |
| 14-search_primary | `discovery_search_primary.py` | 736–864 | data, search_models |
| 15-person_match | `discovery_person_match.py` | 1210–1310 | data |
| 16-icp_score | `discovery_icp_score.py` | 1966–2098 | models |
| 17-region | `discovery_region.py` | 2885–3023 | region_data |
| 18-size | `discovery_size.py` | 3980–4007 | contact_model, size_data |
| 19-company_csv | `discovery_company_csv.py` | 4530–4554 | csv |
| 20-sources | `discovery_sources.py` | 537–691 | data, domains, models |
| 21-search_parse | `discovery_search_parse.py` | 1163–1205 | domains |
| 22-translation | `discovery_translation.py` | 2099–2291 | icp_score |
| 23-lead_score | `discovery_lead_score.py` | 2292–2357 | data, domains |
| 24-person_score | `discovery_person_score.py` | 2358–2489 | data, domains, models |
| 25-country | `discovery_country.py` | 3657–3688 | contact_model, domains, region, region_data |
| 26-contacts | `discovery_contacts.py` | 3689–3857 | contact_data, contact_model, data, domains |
| 27-judge | `discovery_judge.py` | 4008–4090 | domains, region, seed |
| 28-search_fallback | `discovery_search_fallback.py` | 865–1001 | data, domains, search_html, search_models, search_parse |
| 29-linkedin_parse | `discovery_linkedin_parse.py` | 1311–1344 | data, domains, person_score, search_parse |
| 30-employment_parse | `discovery_employment_parse.py` | 1511–1673 | data, person_match, person_score, search_models |
| 31-person_contact | `discovery_person_contact.py` | 2490–2585 | data, domains, models, person_score |
| 32-region_fit | `discovery_region_fit.py` | 3897–3979 | contact_model, country, domains, region, region_data |
| 33-classify | `discovery_classify.py` | 4091–4132 | judge |
| 34-search | `discovery_search.py` | 1002–1025 | search_fallback, search_models, search_primary |
| 35-employment | `discovery_employment.py` | 1674–1799 | data, employment_parse, search_models, search_primary |
| 36-website | `discovery_website.py` | 1026–1162 | data, domains, search |
| 37-linkedin | `discovery_linkedin.py` | 1800–1892 | data, employment, employment_parse, models, person_match, search |
| 38-page_search | `discovery_page_search.py` | 1893–1965 | data, domains, models, search |
| 39-people | `discovery_people.py` | 2586–2791 | data, domains, icp_score, lead_score, linkedin, models, page_search, pages, person_contact, person_score, sources |
| 40-query | `discovery_query.py` | 3157–3258 | domains, models, region, search, search_models, website |
| 41-wiki_parse | `discovery_wiki_parse.py` | 3259–3404 | data, domains, website |
| 42-company_linkedin | `discovery_company_linkedin.py` | 3858–3896 | contact_data, contact_model, search, website |
| 43-wiki | `discovery_wiki.py` | 3405–3512 | icp_score, region, website, wiki_parse |
| 44-company_row | `discovery_company_row.py` | 4174–4361 | company_linkedin, contacts, country, data, domains, icp_score, lead_score, linkedin, models, page_search, pages, person_score, region, region_data, region_fit, size, translation |
| 45-candidates | `discovery_candidates.py` | 3513–3633 | domains, models, query, region, region_data, seed, sources, website, wiki |
| 46-company_pipeline | `discovery_company_pipeline.py` | 4362–4529 | candidates, classify, company_row, domains, judge, models, region, seed, sources, translation |

`discovery.py` ends as a facade below 400 lines. There are 46 units; source spans
are at most 356 lines, leaving import headroom. Data modules are exempt but these
also target <400. Module count favors small, reviewable moves over combining
subsystems. Do not consolidate responsibilities during extraction.

## Compatibility and seams

Re-export each moved definition immediately, preserving object identity for
classes and constants. Preserve shared mutable state and caches; do not copy
objects. Keep existing imported aliases (`_stem`, `fold`, `pick_company_email`,
phone helpers, etc.) accessible from discovery.py.

A re-export does not redirect a moved function's global lookups. Existing tests
patch facade attributes such as web_search and crawl_company_pages. For each
unit, inventory patch/monkeypatch targets: mechanically retarget patches to the
owning/consuming module where lookup now occurs, without changing assertions,
fixtures or public imports. Patch all consumers where required, and retain tests
that exercise facade exports. Do not introduce reverse imports or module proxy
magic to preserve test implementation details. Public function imports remain
unchanged; arbitrary mutation of facade globals is not an advertised API. If a
real caller relies on that behavior, stop and report options to Mehmet.

Existing reverse dependencies require attention: emails.pick_company_email lazily
reads ROLE_PREFIXES, COMPANY_EMAIL_PRIORITY and normalize_domain from discovery;
retarget those reads to data/contact_data/domains once available, preserving
values and semantics. icp_expansion's lazy facade references must similarly use
the owner modules once those are available. Keep imports lazy where needed to
avoid existing cross-module cycles; inspect the entire external dependency path,
not only the table. Never move those dependencies back through the facade.

Preserve filesystem anchors: `_PROJECT_ROOT` and `_REACHER_BIN_DIR` use
Path(__file__).resolve().parents[2]; sibling modules retain that depth. Never
edit/download vendor binaries. Keep local provider/config imports and no-provider
fallbacks. Preserve request limits, sleep ordering, search fallback ordering,
threading, progress callback contents and exception boundaries.

## Rules for coding sessions

1. Start by reading progress.md, features.json and `git log -5`, then run
   `./docs/plans/discovery-split/init.sh`. If it fails, stop and report. Read
   AGENTS.md, relevant architecture and decisions too. Never repair unrelated gates.
2. Do exactly ONE unit: the first one with `passes: false`.
3. Pure move: no behavior changes, no renames unless required. Keep re-exports
   in discovery.py. Do not fix known bugs, edit labels or extend legacy email code.
4. Verify: check.sh green; every eval metric value identical to the exact baseline
   in progress.md; lower discovery.py's ratchet number to its new line count and
   add the new module (under 400 lines) to the ratchet. Never raise a ratchet.
   Inspect the generated eval JSON, since eval.sh reports deltas without failing
   on regressions. Preserve all existing assertions and strict xfails.
5. Stage explicit paths and run `.agents/skills/review/SKILL.md` on the staged diff.
   Fix FAIL findings or record why not. Re-review substantive corrections.
6. Commit the unit, set `passes: true`, then append to progress.md: unit id,
   agent used, wall-clock duration, tokens/cost (from whatever usage summary your
   CLI provides; unavailable if absent), number of check.sh runs, reviewer verdict,
   and any retries or surprises. Then STOP. Persist status/log in a small follow-up
   commit if written after the implementation commit; one logical extraction only.
   Never use --no-verify. Push only with check.sh green, when authorized.
7. If a unit turns out bigger than planned, split it in features.json, update this
   dependency map, commit the plan change, and stop. Report judgement calls with
   options/evidence; do not choose behavior changes for Mehmet.

## Highest-risk units

- website: registrable-domain and name matching determine wrong-company attachment;
  patched search dependencies and ccTLD preferences must keep their semantics.
- company_row: joins crawling, contacts, region, scoring and classification;
  many dependency lookups and optional provider/translation paths converge here.
- company_pipeline: final orchestration owns concurrency, channel merging, judge
  overrides and progress ordering. Preserve unknown/defer semantics and region
  authority; fixed-artifact eval alone cannot detect runtime regressions.

## Harness portability findings

- `.claude/settings.json` and `.claude/hooks/post-edit.sh` use Claude tool names,
  JSON event shape, `$CLAUDE_PROJECT_DIR`, and a system `python`. Keep shared scripts
  as the agent-neutral gates; use thin per-agent adapters rooted via git and .venv.
- Claude-only deny rules in settings cover .env and labels; AGENTS.md protects
  labels for every agent. Add equivalent host permissions per agent as needed.
- `evals/reviewer_eval.sh` requires claude; reviewer_eval.py invokes `claude -p`
  with Claude-specific tools/options. Suggested fix: a reviewer-command adapter
  with normalized verdict/usage output; preserve the labelled cases.
- Review skill requests a fresh subagent when available, with direct-review fallback.
  It works here; prefer capability-based wording, never a named vendor agent.
- No `/cost` dependency found. Usage summaries differ: record supplied numbers
  or unavailable, never require a vendor-specific slash command.
- `.codex/config.toml` declares a Stop hook, but declaration alone does not prove
  runtime activation. Use explicit init/check gates in every session; verify hook
  execution from host events before relying on it. No hook configuration changed.
- Claude model names in product defaults/tests describe supported providers and
  are not harness dependencies.
