#!/usr/bin/env bash
# Quality evals (offline by default). Not part of check.sh.
#   ./scripts/eval.sh [--record] [--discover-csv PATH] [--baseline]
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
if [[ -x .venv/bin/python ]]; then
  export PATH="$PWD/.venv/bin:$PATH"
elif [[ -z "${CI:-}" ]]; then
  echo "No .venv found. Create it: python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi
python -m evals.run_all "$@"
