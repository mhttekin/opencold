# 0002 — Stemming for SIC BM25

- **Status:** adopted — plural-only folding (`sic_index.stem`)
- **Date:** 2026-11-10
- **Reproduce:** `python -m evals.compare_stemmers` (needs `pip install snowballstemmer`
  for the Snowball variant only)

## Context
BM25 over the ONS SIC index needs plural and singular forms to meet ("bakeries" vs
"Bakery"), without fuzzy matching (pallet ≠ pellet). Applied to index and query alike.

## Variants
- **none** — words as-is (after `fold()`).
- **snowball** — Snowball (Porter2) English stemmer.
- **plural** — general plural folding: `-ies`→`-y`; `-es` after s/x/z/ch/sh; else a
  final `-s` (not `-ss`/`-us`/`-is`); never below 3 letters. No word lists.

## Results
Labelled SIC eval (n=6):

| | top-1 | lenient | recall@5 | sibling | abstain |
|---|---|---|---|---|---|
| none | 0.50 | 0.50 | 0.83 | 0 | 0 |
| snowball | 0.67 | 0.67 | 1.00 | 0 | 0 |
| plural | 0.67 | 0.67 | 1.00 | 0 | 0 |

snowball and plural tie on the labelled set, so the tie was broken on the unlabelled
probes (`evals/sic_probes.py`). They differ on three probes; correctness below is the
author's judgement of the SIC meaning, not ground-truth labels:

| probe | snowball | plural |
|---|---|---|
| accountants | 17230 paper stationery ✗ (over-stemmed to "account") | 69201 accounting ✓ |
| galvanising | 24100 basic iron & steel ✗ | 25610 treatment & coating of metals ✓ |
| solar panel installers | 43210 electrical installation ✓ | 16210 veneer sheets, low-confidence (abstains) |

## Decision
Plural-only folding: equal on labelled cases, 2–1 on differing probes, no extra
dependency, and its failure mode is under-matching (abstain) rather than Snowball's
over-stemming ("accountants" → "account" → stationery).

## Limitations
Same labelled set as ADR 0001 (n=6, one SIC area); probe correctness is a judgement
call on 3 differing probes. Revisit with a larger multi-sector labelled set.
