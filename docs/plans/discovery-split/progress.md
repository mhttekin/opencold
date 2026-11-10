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

Record unit id, agent/CLI, starting and ending commit, wall-clock duration,
tokens/cost from CLI usage summary (write unavailable if absent; never estimate),
check.sh run count, exact eval comparison, reviewer verdict, retries/surprises.
The implementation commit is followed by a log/status commit if necessary; never
start another unit in that session.

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
