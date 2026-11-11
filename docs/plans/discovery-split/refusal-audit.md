# Move tool refusal audit — 2026-11-11

Checkout: `f8896bb` (13-search_html complete), 33 pending units. Both sweeps
invoked `.venv/bin/python scripts/move_defs.py <id> --dry-run` separately for
every pending unit against the same source/queue, without performing moves.

| Result/category | Before | After |
|---|---:|---:|
| eligible | 9 | 9 |
| unresolved_dependency | 20 | 20 |
| mutable_state | 4 | 4 |
| total pending | 33 | 33 |

Eligible now: 14-search_primary, 15-person_match, 16-icp_score, 18-size,
19-company_csv, 21-search_parse, 23-lead_score, 24-person_score, 26-contacts.
These passed AST equality, compilation and Ruff import/name checks in memory;
runtime goldens and runner postchecks still gate every actual move.

The most common refusal is a reference to a definition still in a pending
predecessor unit: 25-country, 27-judge through 35-employment, 37-linkedin through
46-company_pipeline. The remaining four refusals are the state guard:
17-region (`_HQ_VERB_RE`), 20-sources (`_PROJECT_ROOT`), 22-translation
(`_NATIVE_FUNCTION_WORDS`), 36-website (`WEBSITE_DIRECTORY_DOMAINS`). The guard
is deliberately conservative and also catches expressions outside its immutable
allowlist; this audit does not assert that each of these objects is mutable.

No transformation coverage was added. Imports from these future owners cannot
pass import checks today because the modules do not exist. Copying their helpers
would duplicate ownership, importing the facade would reverse the dependency
graph, and moving extra definitions would change the selected unit's scope.
The existing mover already obtains the correct imports after predecessors move.
A new disposable-repository test demonstrates the sequence: consumer refused,
predecessor moved, consumer accepted with an owner import and identical AST.
Mutable state remains refused. Thus **9 units are currently tool-eligible,
0 newly eligible**; future eligibility must be rechecked as the queue advances.

Raw per-unit JSON sweeps and a combined CSV are retained in the ignored
`.agent-logs/refusals-before.json`, `refusals-after.json`, and `refusal-audit.csv`.
The runner separately appends actual fallbacks to `.agent-logs/refusals.csv`.

Fallback briefs replace full-plan/progress loading. An example generated for
22-translation is 7,204 bytes versus 33,596 bytes for the original plan plus
progress (79% smaller). This measures supplied context, not total agent tokens;
no paid fallback sessions were run to claim a token reduction. Rules remain in
plan.md; the brief generator extracts the compatibility and coding-session
sections. Progress keeps the baseline/template and five entries, with older
entries preserved in progress-archive.md and prerequisites checked across both.
