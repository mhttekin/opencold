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

Use one short block per unit with its starting commit, extraction result and
verification verdict. Put detailed evidence in the commit body. Include the unit
entry and queue status with its code. See plan.md for the session rules.

- 18-size mode=tool, 3220→3198 lines

- 19-company_csv mode=tool, 3198→3172 lines

- 20-sources mode=agent, start `b54b051`, 3172→3027 lines; new discovery_sources.py 175.
  Tool refused `_PROJECT_ROOT` as mutable_state. Audit: a Path bound once, never
  rebound. Same `parents[2]` depth in the sibling module. No `discovery.<name> =`
  writes, setattr/globals writes or patch targets for it in src/tests/evals/scripts.
  Owner moved discovery→discovery_sources, facade re-exports it. Five tests now patch
  `opencold.discovery_sources._fetch_source`, where the lookup happens. Checks green,
  golden unchanged, eval metrics identical to baseline. Review: PASS.

- 21-search_parse mode=tool, 3027→2986 lines

- 22-translation mode=agent, start `54c9db7`, 2986→2799 lines; new discovery_translation.py 205.
  Tool refused `_NATIVE_FUNCTION_WORDS` as mutable_state. Audit: a set bound once, only
  read via `in`, never mutated or rebound. No `discovery.<name> =` writes, setattr/globals
  writes or patch targets for it in src/tests/evals/scripts. Owner moved
  discovery→discovery_translation, facade re-exports it (identity checked). Tests patch
  `opencold.translator.translate`, so no retargeting needed. Kept `_stem` facade alias.
  Checks green, golden unchanged, eval metrics identical to baseline. Review: PASS.

- 23-lead_score mode=tool, 2799→2734 lines

- 24-person_score mode=tool, 2734→2610 lines
