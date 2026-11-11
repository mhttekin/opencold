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

## 01-data — 2026-11-10 — Codex

Starting commit `ea7ca81`. Moved 39 definitions with AST equality and preserved
facade identity. Ratchet 4,554 → 4,243. Checks passed (691 passed, 2 xfailed),
all recorded eval metrics matched, and review passed. Implementation `2ac256f`.

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

Starting commit `4bc1be4`. Moved CandidateCompany and Contact with AST equality
and preserved facade identity. Ratchet 4,243 → 4,225. Checks passed (692 passed,
2 xfailed), the golden was unchanged, all 20 eval metrics matched, and review passed.

## 03-search_models — 2026-11-10 — Codex

Starting commit `4984569`. Moved SearchResult with AST equality and preserved
facade identity. Ratchet 4,225 → 4,215. Checks passed (692 passed, 2 xfailed),
the golden was unchanged, all 20 eval metrics matched, and review passed.

## 04-reacher — 2026-11-10 — Codex

Starting commit `7349645`. Moved Reacher definitions byte-for-byte. Ratchet
4,215 → 4,058. Checks passed (692 passed, 2 xfailed), the golden was unchanged,
all 20 eval metrics matched, and review passed. Mutable-state audit: the owner
now rebinds `_REACHER_BIN`; facade reads share the live cache. No facade writes
or cache patches were found. Reacher mocks target the owner; MX mocks target
verifier. A mocked lookup confirmed both call paths share one cache.

## golden-v2 — done

- Added `discover_golden_v2.json` alongside the original snapshot, whose nine
  rows are byte-identical. The new fixture records full row values, field order,
  ranking and progress for judged and timeout runs with a fake provider.
- Judge coverage: Ashmill is verified on a positive judge verdict despite no
  deterministic industry match. Birch is rejected by a negative verdict despite
  a deterministic match. Unknown leaves Cedar verified and Drift in review.
  Fjord is rejected on deterministic region conflict despite a positive judge
  verdict. On timeout, deterministic evidence verifies Birch and Cedar, and
  Ashmill and Drift go to review.
- Website coverage: a matching subdomain resolves to `ashmill.co.uk`, ahead of
  a `.com` namesake. Misbound's only search result is an unrelated registrable
  domain, which does not attach.
- Progress coverage: all 20 subprocess runs (`PYTHONHASHSEED` 1 through 20)
  matched the raw sequence with three workers. Every fixture worker returns a
  row, so completion order cannot affect cumulative counts. The fake monotonic
  clock advances by 0.25 seconds, and scores within each confidence band are
  distinct. The golden compares the sequence directly.
- Mutation proofs: ignoring yes, ignoring no, rejecting explicit unknown, and
  letting yes override a region conflict each broke judged-row equality.
  Propagating the timeout failed the timeout case. Substituting the absolute
  clock value failed progress equality at event one (`100.25` vs `0.25`).
  Truncating the public suffix yielded `https://co.uk`, allowing a fallback
  attached `https://unrelated.co.uk`, and ignoring the country preference changed
  the selected row. Each failed row equality. All nine mutations were reverted.
- Added prerequisite tags for 25 pending units covering resolution, verification
  and orchestration. No extraction status changed.

## 05-contact_data — 2026-11-10 — Codex

Starting commit `4f09738`. Moved five contact definitions with AST equality and
facade identity. Ratchet 4,058 → 4,018. Checks passed (717 passed, 2 xfailed),
both goldens were unchanged, all 20 eval metrics matched, and review passed.
Mutable-state audit: the `COMPANY_EMAIL_PRIORITY` dict moved to the owner without
copying or rebinding. No facade writes, mutations or patches were found. Git
writes were blocked in the agent session; `dbec356` completed the unit.

## 06-region_data — 2026-11-11 — Codex

Starting commit `bde213e`. Moved 12 region definitions with AST equality and
preserved facade identity into a 47-line owner. Ratchet 4,018 → 4,011. Checks
passed (732 passed, 2 xfailed), both goldens unchanged, all 20 eval metrics
matched, and review passed. State audit: `_REGION_CCTLD`, `_REGION_PHONE`,
`_REGION_CITIES`, `_REGION_LANGS`, `_REGION_ALIASES`, `_COUNTRY_NAMES`,
`_COUNTRY_DEMONYMS`, `_AMBIGUOUS`, `_PHONE_CC`, `_COUNTRY_NAMES_BY_LEN` and
`_COUNTRY_DEMONYMS_BY_LEN` moved from discovery to discovery_region_data; direct
re-exports share objects, including nested lists. No runtime rebinding, facade
writes, dynamic writes or patches targeting these names were found; no patch
retargeting was required. The move tool refused mutable state, so extraction was
manual. Loop session: left unstaged and uncommitted for the runner.

## 07-size_data — 2026-11-11 — Codex

Starting commit `993bf19`. Moved two compiled regex constants with AST equality
and preserved facade identity into a 12-line owner. Ratchet 4,011 → 4,003.
Checks passed (732 passed, 2 xfailed), both goldens unchanged, all 20 eval metrics
matched, and review passed. The regex objects are immutable; no mutable state
moved. No writes, dynamic writes or patches targeting either constant were found;
`size_tier` continues to read the facade imports. Loop session: left unstaged and
uncommitted for the runner.

## 08-seed — 2026-11-11 — Codex

Starting commit `8644ff0`. Moved five seed definitions with AST equality and
preserved facade identity into a 127-line owner. Ratchet 4,003 → 3,886. Checks
passed (732 passed, 2 xfailed), both goldens unchanged, all 20 eval metrics
matched, and review passed. No mutable state moved; no facade or dynamic writes
were found for the moved names. The seeding resolver patch now targets its owner;
the candidate-harvest patch stays at its consuming facade. Retargeted the lazy
JSON-parser import in icp_expansion to the owner. Loop session: left unstaged and
uncommitted for the runner.

- 09-contact_model mode=tool, 3886→3859 lines

## 10-csv — 2026-11-11 — Codex

Starting commit `1176153`; mode=agent. Moved three CSV definitions with AST
equality and facade identity into a 41-line owner. Ratchet 3,859 → 3,820.
Checks passed (748 passed, 2 xfailed), both goldens unchanged, all 20 eval
metrics matched, and fresh review passed. State audit: `COMPANY_CSV_FIELDS` and
`COMPANY_PEOPLE_FIELDS` moved from discovery to discovery_csv; direct re-exports
share the original list objects. No runtime mutations/rebinding, facade writes,
dynamic writes or patches of the moved names were found; no patch retargeting
was required. Left unstaged and uncommitted for the runner.

## 11-domains — 2026-11-11 — Codex

Starting commit `3f4aa91`; mode=agent. Moved 13 domain definitions with AST
equality and facade identity into a 136-line owner. Ratchet 3,820 → 3,731.
Checks passed (748 passed, 2 xfailed), both goldens unchanged, all 20 eval
metrics matched, and fresh review passed. State audit: `_SECOND_LEVEL_TLDS`,
`_AGGREGATOR_DOMAINS` and `_AGGREGATOR_STEMS` moved from discovery to
discovery_domains; direct re-exports share the original sets. No runtime
mutations/rebinding, facade writes, dynamic writes or patches targeting these
sets were found. Existing normalize_domain patches remain at their consuming
smearch facade; no moved helper patches required retargeting. Retargeted the
email helper's lazy normalize_domain import to its owner. Left unstaged and
uncommitted for the runner.

- 12-pages mode=tool, 3731→3716 lines

- 13-search_html mode=tool, 3716→3705 lines
