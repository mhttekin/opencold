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

- 30-employment_parse mode=tool, 2168→2013 lines

- 31-person_contact mode=tool, 2013→1918 lines

- 32-region_fit mode=tool, 1918→1831 lines

- 33-classify mode=tool, 1831→1794 lines

- 34-search mode=agent, finished manually; agent sandbox blocked pytest, 1794→1777 lines

- 35-employment mode=tool, 1777→1652 lines

- 36-website mode=agent, 1652→1518 lines. State move: WEBSITE_DIRECTORY_DOMAINS
  discovery → discovery_website (re-exported, same object). Audit: no writes, no
  facade/dynamic writes, no patch targets; read only by _is_directory_domain.

- 37-linkedin mode=agent, 1518→1429 lines. No state moved (function only; its
  constants stay in discovery_data).

- 38-page_search mode=agent, 1429→1362 lines. No state moved (functions only; the
  SEARCH_* constants stay in discovery_data).
