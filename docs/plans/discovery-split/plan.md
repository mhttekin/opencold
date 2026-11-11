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
2. Do exactly ONE unit: the first one with `passes: false`. If it has a
   `requires` value, a matching `## <requires> — done` heading must exist in
   progress.md before the session starts that unit. If it is missing, stop and
   report the unmet prerequisite.
3. Pure move: no behavior changes, no renames unless required. Keep re-exports
   in discovery.py. Do not fix known bugs, edit labels or extend legacy email code.
   In a manual session, first run `.venv/bin/python scripts/move_defs.py <unit-id>`.
   In an agent-mode loop session, read the runner's tool attempt log and proceed
   with the extraction after the runner restores the checkout. Read only the
   relevant definitions and direct dependencies in discovery.py. Update the
   ratchet and any consumer imports or test patches separately as needed.
   Moving mutable module-level state, including globals rebound at runtime and
   caches, is not a pure move. Record each state move and its old and new owner
   in progress.md. Grep for writes through the facade (`discovery.<name> = ...`)
   and check for dynamic writes and patch targets. Confirm tests patch the owner
   module where the state is read or written, and record the audit results.
4. Verify: check.sh green; the golden test passes unchanged; every eval metric
   value identical to the exact baseline in progress.md. The discover eval scores
   a fixed CSV and does not exercise runtime code; it is only a sanity check.
   Lower discovery.py's ratchet number to its new line count, or remove its
   exception once it reaches 400 lines. New modules must fit the 400-line limit.
   Inspect the generated eval JSON, since eval.sh reports deltas without failing
   on regressions. Move the generated, untracked report into `.agent-logs/` after
   comparing it so it does not leave the tree dirty. Preserve all existing
   assertions and strict xfails.
5. Run `.agents/skills/review/SKILL.md`. In manual sessions, stage explicit paths
   and review the staged diff. In agent-mode loop sessions, review an unstaged patch covering
   both tracked changes and new files. Include new files with
   `git diff --no-index /dev/null <path>` (exit 1 means there are differences).
   Fix FAIL findings or record why not. Re-review substantive corrections.
6. Set `passes: true` and append one short block to progress.md using the template
   below. Include `mode=agent` in the progress entry for loop sessions.
   Put timing, test runs, verification evidence and surprises in the
   commit body. Under the loop, write that body to the file named by
   `OPENCOLD_UNIT_NOTES` and leave changes uncommitted and unstaged.
   The runner verifies, stages, commits, pushes and checks CI. In manual sessions,
   commit the unit's code and progress/status update in one commit, push to
   `origin/main` and confirm CI is green on all Python versions. Then STOP.
   Never use --no-verify. Use the resulting commit/CI run as the ending reference;
   do not create a separate log/status commit to record its own hash or CI result.
7. If a unit turns out bigger than planned, split it in features.json, update this
   dependency map, and stop. Manual sessions commit the plan change. Loop sessions
   leave it uncommitted for inspection. Report judgement calls with options/evidence;
   do not choose behavior changes for Mehmet.

## Running multiple sessions

```sh
scripts/run_units.sh --agent codex --max-units 3 --dry-run
scripts/run_units.sh --agent codex --max-units 1 --preflight-only
scripts/run_units.sh --agent claude --max-units 3 --timeout-min 20 --push-every 2
```

Use the project `.venv` and authenticate Git and `gh`. Agent fallback needs an
authenticated agent CLI. Dry-run checks the next pending unit against the local
and live remote `main` and prints the starting state. Only one runner can operate
on the checkout at a time.

After checking the unit's prerequisite, the runner calls `move_defs.py` directly.
In tool mode, it updates the ratchet, marks the unit done, and appends one
`mode=tool` progress line with the before and after line counts. The move tool's
AST equality, unchanged goldens, `check.sh`, and the expected changed paths
gate the commit. If the tool refuses or a postcheck fails, the runner restores the
pre-unit checkout and starts a fresh agent-mode session. The session defaults to
20 minutes and follows the coding-session rules above, including review.

- Codex uses `exec --json --ignore-rules`, workspace-write with shell networking
  disabled, and approval policy `never`. `--ignore-user-config` skips user
  settings, and CLI overrides disable plugins and bundled skills.
  [Codex CLI](https://learn.chatgpt.com/docs/developer-commands#codex-exec)
- Claude uses `-p --output-format stream-json --verbose`, `dontAsk`, and the Bash sandbox with
  unsandboxed retries disabled, an empty network allowlist, and write denials for
  Git metadata. `--setting-sources project` selects project settings, and
  `disableBundledSkills` turns off bundled skills.
  [Claude CLI](https://code.claude.com/docs/en/cli-reference) ·
  [Claude sandbox](https://code.claude.com/docs/en/sandboxing)

The runner gives the agent a temporary `HOME` and sets its config directory
there. It copies any file-based login into that directory and removes the
directory when the runner exits. Each CLI applies its own shell sandbox.
[Codex config](https://developers.openai.com/codex/config-advanced) ·
[Claude settings](https://code.claude.com/docs/en/settings)

Claude's macOS Keychain login is tied to its config directory. For a Keychain-only
login, supply `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` or a valid
`ANTHROPIC_API_KEY` in the runner environment.
[Claude authentication](https://code.claude.com/docs/en/authentication#credential-management)

Before the first agent fallback, the runner starts one preflight session
with the same launch settings as agent-mode units. The recorded shell result must
show a successful `pwd` in the checkout, and the CLI must advertise only the
repository `review` skill. Any failure stops the run before the agent session starts.
`--preflight-only` runs this check without starting a unit. Its stdout and
stderr go to `.agent-logs/preflight-<agent>-<timestamp>/`.

Each `.agent-logs/<unit>-<timestamp>/` directory contains the starting commit,
passes count, discovery line count, and SHA-256 hashes of both golden snapshots
in `before.json`. The tool attempt and validation output go to `checks.log`.
Agent fallbacks also write `stdout.jsonl` and `stderr.log`. The ignored
`.agent-logs/usage.csv` includes a `mode` column. Tool rows record elapsed move and
validation time with zero tokens. Agent rows retain the CLI's token accounting.

The runner stages explicit paths and commits each unit as
`Split discovery: <unit-id> (tool)` or `Split discovery: <unit-id>` for agent mode.
`--push-every N` defaults to one and pushes every N commits plus any final partial
batch on a normal exit. The runner checks CI for the pushed HEAD before continuing.
On failure it stops and prints the log location and any commit range since the
last green push, using the starting synchronized tip for the first batch.
Inspect the worktree, unpushed commits, and CI before resuming.

## Runtime characterization golden

`tests/test_discover_golden.py` runs `discover_company_rows()` offline against ten
fake companies, capturing nine complete returned rows in
`tests/fixtures/discover_golden.json`. Candidate harvesting, website resolution,
crawling, contact extraction, translation orchestration, scoring, classification,
and ranking run normally. Search, HTML fetching, translation responses, Wikipedia
names and the clock are fixture inputs; provider config is empty and isolated.
Expansion is disabled. Workers are set to one and scores within each confidence
band are distinct, so completion timing cannot reorder tied rows. Exact row values,
row order and field order are checked, including internal verification flags.

The original snapshot was captured from the post-`01-data` runtime. The companion
`tests/fixtures/discover_golden_v2.json` captures complete rows and ordered
progress callbacks for two provider runs. Both use an isolated fake provider,
three workers, and a deterministic clock. The judge returns yes, no and unknown
in one run and times out in the other. LLM-seeded names exercise `.co.uk`
resolution and rejection of an unrelated domain. Progress events contain only
cumulative counters and elapsed time. All fixture workers return rows, so their
completion order cannot affect the counters. Distinct scores within each
confidence band make the ranked rows independent of completion order too.

Regenerating or changing existing entries in either snapshot requires Mehmet's
explicit approval. Never refresh them to make an extraction pass. Retarget only
transport mocks as their lookup owners move, preserving fixture inputs and
assertions. The review skill's rule 8 protects the original snapshot. The discover
fixed-CSV eval and SIC eval do not replace these runtime checks.

### Session entry template

Use a unit heading with date and agent, followed by a short paragraph recording
the starting commit, extraction result and verification verdict. Include a short
state audit when required by rule 3. The unit commit and CI run are the ending
reference. Keep detailed evidence in the commit body and token usage in the
ignored CSV when the CLI supplies it.

Include this entry and `passes: true` with the code in the same commit. Push and
verify the CI matrix (Python 3.11, 3.12 and 3.13) before reporting completion.

## Highest-risk units

- website: registrable-domain and name matching determine wrong-company attachment;
  patched search dependencies and ccTLD preferences must keep their semantics.
- company_row: joins crawling, contacts, region, scoring and classification;
  many dependency lookups and optional provider/translation paths converge here.
- company_pipeline: final orchestration owns concurrency, channel merging, judge
  overrides and progress ordering. Preserve unknown/defer semantics and region
  authority; fixed-artifact eval alone cannot detect runtime regressions.

## Harness portability

Fixed before coding sessions (2026-11-10):

- Shared gates remain in `scripts/check.sh` and `scripts/fix-file.sh`.
  `scripts/agent-check.sh` captures all check output in unique, gitignored
  `.agent-logs/check.*` files, returning only a failure reason with the last 30
  log lines. Per-agent adapters handle the host event and output protocol.
- Codex: `.codex/config.toml` calls `scripts/agent-hooks/codex-stop.sh`.
  The Python helper reads the Stop JSON from stdin using `.venv/bin/python`.
  Success exits 0 with `{}`; first failure exits 0 with JSON
  `{"decision":"block","reason":"..."}` to request one continuation.
  If `stop_hook_active` is true, another failure exits 0 with a `systemMessage`
  warning pointing to `.agent-logs/check.*`, without a blocking decision.
  Contract: [official Stop documentation](https://learn.chatgpt.com/docs/hooks#stop).
  Direct adapter runs verified all paths using real check.sh runs: passing checks
  produced `{}`; a temporary failing pytest produced block JSON on the first
  attempt and a non-blocking warning when already active. The temporary test was
  removed afterwards. Unit tests exercise crafted inputs without running check.sh.
- After changing `.codex/config.toml` hooks: restart Codex and re-trust them via /hooks.
- Claude: `.claude/settings.json` and its thin post-edit adapter resolve the repo
  via git, without `$CLAUDE_PROJECT_DIR` or system `python`. The adapter parses
  Claude's event with `.venv/bin/python` and delegates to shared `fix-file.sh`.
  Claude-specific tool names and JSON parsing stay in the adapter/settings.
- Reviewer eval: `AGENT_CLI=claude|codex ./evals/reviewer_eval.sh` selects the CLI
  (default `claude`). `scripts/reviewer_agent.py` isolates CLI commands, read-only
  settings and output/usage decoding. Claude uses JSON; Codex uses JSONL and a
  read-only sandbox with approvals disabled. Codex reviewer sessions disable the
  workspace Stop hook so a review does not run a mutating validation gate.
  Results record agent, normalized verdict/rules, supplied token/cost numbers
  (null if unavailable), invocation errors and raw output. CLI failures cannot
  count as valid verdicts. Labelled cases and grading policy are preserved.
  Offline adapter tests cover both CLIs, malformed/failed/incomplete output and
  usage normalization; no paid reviewer comparison was run for this change.

Remaining host-specific work and limits:

- A successful direct adapter run does not prove host event activation. Confirm
  Stop execution/trust in a new Codex session and PostToolUse execution in Claude
  before relying on hooks. Explicit init/check gates remain required every session.
- Claude-only deny rules cover .env and labels; AGENTS.md protects labels for
  every agent. Configure equivalent host permissions where supported; the repo
  does not provide a portable deny-rule format across hosts.
- The review skill uses a fresh subagent when available and direct review otherwise.
  For an agent's own session tokens/cost, write `unavailable`; the operator fills
  in that field. No `/cost` dependency.
- The reviewer runner supports the two named CLIs, not arbitrary CLI syntax.
  Installed CLI authentication, host permissions and live model quality still
  require host-specific validation. Other agents can run the shared gates directly.
- Claude model names in product defaults/tests describe supported providers and
  are not harness dependencies.
