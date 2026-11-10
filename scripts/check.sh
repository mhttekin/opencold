#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
if [[ -x .venv/bin/python ]]; then
  export PATH="$PWD/.venv/bin:$PATH"
elif [[ -z "${CI:-}" ]]; then
  echo "No .venv found. Create it: python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi
ruff format --check .
ruff check .
python -m pytest -q
