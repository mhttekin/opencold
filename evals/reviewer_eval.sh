#!/usr/bin/env bash
# Eval the review skill: each patch in evals/reviewer/cases/, twice, in fresh
# headless Claude Code sessions. Costs model usage; not part of check.sh or CI.
#   ./evals/reviewer_eval.sh [--runs 2] [--workers 4] [--only NAME]
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
if [[ -x .venv/bin/python ]]; then
  export PATH="$PWD/.venv/bin:$PATH"
fi
command -v claude >/dev/null || { echo "claude CLI not found" >&2; exit 1; }
python -m evals.reviewer_eval "$@"
