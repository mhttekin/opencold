---
name: review
description: Review a staged diff or commit range against AGENTS.md invariants and report concrete violations. Use before committing non-trivial changes.
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git log:*), Bash(git show:*)
---

# Invariant review (inferential sensor)

You are a reviewer, not the author. Judge only the diff in front of you.

## Fresh context
If you can spawn a subagent, hand this whole file plus the diff to a fresh subagent
and report its result verbatim, so the review isn't graded by the context that wrote
the change. If you can't, review directly and judge only the diff text.

## Input
- No argument: `git diff --staged`.
- A commit range (e.g. `main..HEAD`, `abc123~1..abc123`): `git diff <range>`.
- A path to a `.patch`/`.diff` file: read that file. Do NOT apply it.

## Read first
1. `AGENTS.md` (invariants, gotchas, conventions).
2. Every file in `docs/decisions/`.
3. The sections of `docs/architecture.md` for the code the diff touches.
Open the touched source files only as far as you need to judge a hunk in context.

## Check ONLY these rules
Computational sensors (ruff, pytest, the invariant tests) already cover lint, format,
CSV columns, CLI flag sync, headless pipeline imports and module size. Do not repeat them.

1. **LLM `unknown` never rejects.** The LLM owns industry judgement; deterministic
   signals own region. Flag a change where an LLM `unknown` (or a failed/absent LLM
   call) leads to rejection, or where the LLM overrides a deterministic region signal.
2. **New LLM path without fallback.** Any new LLM call must have a deterministic or
   keyless path when no provider is configured or the call fails.
3. **Secrets in progress callbacks.** No API keys, tokens, passwords or provider
   config in dicts passed to `pipeline.py` progress callbacks.
4. **Language- or country-specific special cases.** Hard-coded countries, TLDs,
   scripts or words inside matching/normalization/region logic (data tables in
   `regions_data.py`-style data modules are fine; `if region == "turkey"` is not).
5. **Making evals easier without making the product better.** Scorer edits that drop
   or soften a metric, thresholds tuned to labels, special-casing eval inputs, or edits
   under `evals/labels/`.
6. **Re-trying a rejected/not-adopted approach** from `docs/decisions/` without new
   evidence stated in the diff or commit message.
7. **Legacy email code extended** (`generator`, `prompts`, `sender`, `run`/`draft`/`send`):
   new features there are a violation; deletions or bug fixes are not.
8. **Tests weakened.** Assertions removed or loosened, tests deleted, or `xfail`/`skip`
   added to make the suite pass rather than to pin a real, unfixed bug. Regenerating
   or changing `tests/fixtures/discover_golden.json` without Mehmet's explicit
   approval is also a violation; never refresh it to make an extraction pass.

Never report lint, formatting or test failures.

## Output
For each finding:

```
[R<n>] <file>:<line>
> <short quoted line from the diff>
<one or two sentences: why this violates rule n>
```

No speculative findings: if you are not sure a line violates a rule, don't report it.
Then end with exactly one line: `VERDICT: PASS` (no findings) or `VERDICT: FAIL`.
