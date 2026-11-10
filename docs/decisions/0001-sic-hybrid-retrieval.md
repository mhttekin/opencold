# 0001 — Hybrid (BM25 + embedding) SIC retrieval

- **Status:** not adopted for now (not rejected)
- **Date:** 2026-11-10
- **Implementation:** commit `f7b2203` ("Add optional hybrid SIC retrieval (BM25 + model2vec, RRF)");
  `git show f7b2203` / `git revert` of the removal commit restores it.

## Context
smearch maps an ICP to SIC codes from two offline sources: SIC-title term overlap and
BM25 over the ONS alphabetical index (~16k activity phrases). The question was whether
adding dense retrieval improves code ranking.

## What was tried
- model2vec static embeddings of every ONS index row; per-code score = **max cosine
  over that code's index rows** (BM25 likewise uses the code's best-scoring row).
- Fusion with the BM25 ranking by Reciprocal Rank Fusion (k=60, normalised by its
  maximum; weights not tuned).
- Two models: `minishlab/potion-multilingual-128M` (default; 506 MB, dim 256) and
  `minishlab/potion-retrieval-32M` (125 MB, dim 512). Embedding all 15,956 rows takes
  ~0.1 s; warm model load ~1.8 s / ~0.5 s.

## Results (labelled SIC eval, `evals/results/2026-11-10-f7b2203*.json`)

| | lexical | hybrid 128M | hybrid 32M |
|---|---|---|---|
| top-1 | 0.67 | 0.33 | 0.33 |
| top-1 lenient | 0.67 | 0.33 | 0.33 |
| recall@5 | 1.00 | 0.83 | 0.83 |
| sibling confusion | 0 | 0 | 0 |

Probe ICPs (`evals/sic_probes.py`, unlabelled): low-confidence/empty answers dropped
from 7 to 4 in hybrid mode — the embedding list always yields a "nearest" code, so the
abstention gate fires less (e.g. "car dealerships" no longer stops).

## Limitations
- n = 6 labelled cases, all from one SIC area (16/22: wood, pallets, plastics).
- Only static (non-contextual) embedding models.
- Only one fusion method (RRF) and one per-code aggregation (max over rows).

## Conclusion
No improvement was shown on this set, and there is an observed cost (weaker
abstention on probes). This is **not** evidence that embeddings don't help SIC
matching; the test was too narrow to say that.

## Revisit if
- the labelled set covers several sectors (20+ cases), or
- a contextual embedding model (e.g. EmbeddingGemma) is tested, or
- cross-lingual matching is needed in discover.
