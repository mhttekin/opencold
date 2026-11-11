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

- 12-pages mode=tool, 3731→3716 lines

- 13-search_html mode=tool, 3716→3705 lines

## Runner context and refusal audit — 2026-11-11 — Codex

Starting commit `f8896bb`; no extraction unit or queue status changed. Added JSON
refusals, read-only move validation, runner refusal CSV and scoped fallback briefs.
Compacted older progress into progress-archive.md, preserving baseline and
prerequisite checks across both files. Both 33-unit dry-run sweeps: 9 eligible,
20 unresolved predecessor dependencies, 4 state-guard refusals. No safe coverage
extension was needed: existing owner imports resolve after predecessors move;
mutable state remains refused. Full checks passed (755 passed, 2 strict xfails);
fresh invariant review: PASS. See refusal-audit.md for evidence and limitations.

- 14-search_primary mode=tool, 3705→3577 lines

- 15-person_match mode=tool, 3577→3472 lines
