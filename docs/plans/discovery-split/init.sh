#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.."
if [[ ! -x .venv/bin/python ]]; then
  echo "Missing executable .venv/bin/python; create the project environment first." >&2
  exit 1
fi
.venv/bin/python --version
./scripts/check.sh
./scripts/eval.sh
wc -l src/opencold/discovery.py
