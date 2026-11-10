#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
ruff format --check .
ruff check .
python -m pytest -q
