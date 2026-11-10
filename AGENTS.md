# OpenCold

CLI for ICP-based company discovery and enrichment (`discover`, `smearch`, `prepare`).
User-facing usage: README.md. Pipeline internals: docs/architecture.md. Read the
relevant section before changing discovery, smearch, or pipeline code.

## Commands
- Install: `pip install -e ".[dev]"` (src layout: `src/opencold`)
- Use the project venv (.venv), not conda base. Fish: source .venv/bin/activate.fish
- Check everything: ./scripts/check.sh (format, lint, tests). Run before finishing any task.
- Testing edits from another checkout/worktree: prefix `PYTHONPATH=<checkout>/src`,
  otherwise the installed copy runs.

## Invariants
- Works with no LLM provider. LLM tiers (seeding, judge, expansion) stay
  provider-pluggable and degrade to keyless/deterministic. Callers may inject their own model.
- Verification: the LLM owns industry judgement, deterministic signals own region.
  LLM `unknown` defers to deterministic and never rejects.
- `pipeline.py` is headless so it can be embedded in an API: no disk config, prompts,
  printing, or file writes. Progress goes out via callback of plain dicts, never secrets. (enforced: tests/test_invariants.py)
- Tests never touch real config: use `tmp_config` / `seeded_config` (tests/conftest.py).
- Tests never hit the network (enforced by pytest-socket via `addopts`).
- Output CSV columns are a contract. Renaming one means updating README and tests together. (enforced: tests/test_invariants.py)
- Respect rate limits. Never add CAPTCHA solving or anti-bot evasion.

## Gotchas
- CLI flags live in three places: Typer signature, `_parse_<cmd>_args()`, REPL help text.
  Change all three. (enforced: tests/test_invariants.py)
- Wrong-company attachment usually comes from `resolve_company_website()`
  (`_registrable_domain`, name↔domain matching).
- Email drafting/sending (`generator`, `prompts`, `sender`, `run`/`draft`/`send`) is legacy:
  don't extend it, don't delete it without asking, never run `send`.
- `server/` (FastAPI) and `web/` (Next.js) were archived to branch `archive/server-web`.
  Don't recreate them.
- `vendor/bin/` holds the auto-downloaded Reacher binary. Don't edit or commit it.

## Conventions
- Logic modules stay under ~400 lines (data modules exempt), enforced by a ratchet in
  tests/test_invariants.py; lower the number when you shrink a file.
- README stays terse: one short entry per feature, no mechanism explanations.
- Ratchet numbers only go down. Raising one requires asking first.

## Git
- Never use git commit --no-verify.
