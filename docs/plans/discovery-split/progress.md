# Discovery split session log

## Baseline — 2026-11-10 — Codex initializer

- Starting commit: `5ef9330`; working tree clean before initializer.
- Python: `.venv/bin/python`, 3.13.2.
- `./scripts/check.sh`: PASS; 675 passed, 2 xfailed, 4.68 seconds.
- `./scripts/eval.sh`: exit 0, offline; current values below are the split baseline.
- `src/opencold/discovery.py`: 4,554 lines; existing ratchet 4,554.
- Stored `evals/results/baseline.json` predates SIC improvements: top1/lenient 0,
  recall@5 2/3, sibling confusion 1. Do not overwrite it; compare split sessions
  against the exact current values below instead. Discover metrics match it.
- Discover eval scores the fixed artifact `evals/artifacts/discover_tr_pallets_2026-11-10.csv`;
  it does not exercise the refactored runtime. Unit tests remain essential.

```json
{
  "sic": {
    "cases": 6,
    "abstain": 0,
    "top1_accuracy": 0.6666666666666666,
    "top1_lenient": 0.6666666666666666,
    "recall_at_5": 1.0,
    "sibling_confusion": 0
  },
  "discover": {
    "output_rows": 17,
    "verified": 7,
    "unlabelled_rows": 0,
    "precision": 1.0,
    "recall": 0.6363636363636364,
    "no_match_verified": 0,
    "exclude_verified": 0,
    "exclude_leakage": 5,
    "exclude_total": 5,
    "name_accuracy": 0.16666666666666666,
    "invalid_emails": 1,
    "phones_valid_e164": 7,
    "phones_local_unnormalized": 4,
    "phones_garbage": 1
  }
}
```

## Session entry template

Record unit id, agent/CLI, starting commit, wall-clock duration, tokens/cost
(`unavailable`; the operator fills it in), check.sh run count, unchanged golden,
exact eval comparison, reviewer verdict, retries/surprises. Include code, this
entry and queue status in ONE commit, then push and confirm the full Python CI
matrix is green. The resulting commit/CI run is the ending reference; do not make
a follow-up commit to record its own hash or CI result. Never start another unit
in that session. See plan.md for the field template.

## 01-data — 2026-11-10 — Codex

- Starting commit: `ea7ca81`; implementation ending commit: `2ac256f`.
  This entry and queue status are persisted in the follow-up log commit.
- Agent/CLI: Codex (GPT-6); fresh review subagent: `review_unit_01`.
- Wall-clock timed implementation/review interval: 2m 13s
  (21:58:08–22:00:21 UTC); initial reading/init occurred before that interval.
- Tokens/cost: unavailable (no CLI usage summary supplied).
- Moved all 39 owned definitions, unchanged by AST comparison, into
  `discovery_data.py` (357 lines). Facade exports retain object identity;
  `emails.pick_company_email` now lazily reads `ROLE_PREFIXES` from its owner.
  Other lazy dependencies remain for their queued owner extractions.
- Patch inventory: no tests patch the moved constants; no patch retargeting needed.
  Added facade identity coverage without changing existing assertions or xfails.
- `discovery.py`: 4,554 → 4,243 lines; ratchet lowered to 4,243.
  The new module is covered automatically by the ratchet's source glob and its
  400-line default; it is not exempted as data or grandfathered.
- `check.sh`: 3 explicit runs, including initializer; all PASS.
  Final result: 691 passed, 2 xfailed. Commit hooks also passed ruff checks.
- Eval: all 21 metric values exactly equal the baseline above, verified against
  the generated JSON, not the older `baseline.json`. Result retained at
  `evals/results/2026-11-10-ea7ca81.json`. Final eval rerun also matched exactly.
- Reviewer output: `VERDICT: PASS` (no findings).
- Retries/surprises: grouped self-alias imports expanded under ruff; compacted
  imports while retaining the unused private pattern's explicit re-export.
  The initial comparison script read the JSON suite root instead of `metrics`;
  corrected the inspection and confirmed exact equality. Git staging required
  sandbox escalation. No implementation behavior changes or failed check runs.
- Stopped after this unit; next pending unit is `02-models`.

## Harness hardening before 02 — 2026-11-10 — Codex

- Starting commit: `318130f`; no extraction unit started or queue status changed.
  This single commit contains the harness code, golden and documentation updates;
  its pushed CI run is the ending reference.
- Tokens/cost: `unavailable` (operator fills in).
- Added `tests/test_discover_golden.py` and initially captured
  `tests/fixtures/discover_golden.json` from the unchanged post-01 runtime.
  All returned fields, internal flags, field order and row order are compared.
  The empty `tmp_config` exercises actual no-provider resolution with LLM use
  enabled. Search, HTML transport, Wikipedia names, translation responses and the
  clock are mocked; extraction/scoring/classification/ranking remain real.
  Expansion is disabled; optional people search is outside this characterization.
- Fixture coverage (10 fake companies, 9 returned rows):

  | Company | Branches/signals |
  |---|---|
  | Atlas Pallets | verified; Wikipedia/search dedup; ccTLD, phone and address; JSON-LD, mailto, person email, LinkedIn, partnership page; searched team page merged with crawled pages; enterprise size |
  | Boreal | verified; phone-only region anchor; role inbox and email partnership channel; SME size |
  | Cedre | verified; address-only region anchor; no email; mid size |
  | Durable | verified; native French ICP evidence, ccTLD; micro size |
  | Iris | verified; French facts translated on a miss, ccTLD |
  | Guide | review; directory-like content despite ICP and ccTLD evidence |
  | Eclat | review; ICP evidence with no region anchor |
  | Hollow | review; unresponsive website, no facts/contacts, ccTLD only |
  | Fjord | rejected; foreign ccTLD region conflict despite ICP evidence |
  | Invisible | no website; Wikipedia name resolves only to a directory listing and is omitted |

- Mutation proof: temporarily changed the ICP score base from 35 to 36 in
  `score_company`. The golden test failed at exact row equality (Atlas's
  `icp_score` changed from 49 to 50). Restored discovery.py byte-for-byte; the
  unchanged golden test then passed. Golden SHA256 remained
  `bf4182095cab3c4bfc7018e6deaacfa5f23f95cd91e2d06c4fa603838050012e`.
- Validation: `check.sh` PASS (692 passed, 2 strict xfails retained); golden also
  passed in separate processes with PYTHONHASHSEED 1, 7 and 42. All 21 generated
  eval metrics exactly match the baseline above; result retained at
  `evals/results/2026-11-10-318130f.json`. The review skill validator passed.
- Plan now requires an unchanged runtime golden, one code/status commit, push and
  a green Python CI matrix; golden regeneration requires Mehmet's explicit
  approval and is protected by review rule 8. No production code changes remain.
- Fresh invariant reviewer: `VERDICT: PASS` (no findings).

## 02-models — 2026-11-10 — Codex

- Agent/CLI: Codex (GPT-6), with fresh review by `review_unit_02`.
- Starting commit: `4bc1be4`. Ending reference: this commit and its CI run.
- Wall-clock duration through verification and review: about 1m 18s.
- Tokens/cost: `unavailable` (operator fills in).
- Moved `CandidateCompany` and `Contact` with identical class definitions by AST
  comparison. The facade exports are the same objects as the owner exports.
  Neither class had patch targets to retarget.
- `discovery.py` ratchet: 4,243 → 4,225 lines. The 24-line `discovery_models.py`
  is covered by the ratchet's source glob and 400-line default.
- `check.sh`: two explicit runs, including the initializer. Both passed with
  692 passed and 2 xfailed. The unchanged runtime golden also passed separately.
  All 20 metrics in the exact baseline JSON above matched the generated eval JSON.
- Reviewer verdict: `VERDICT: PASS`.
- Retries/surprises: no implementation retries. The baseline JSON contains 20
  metric keys. The earlier log counted 21.
