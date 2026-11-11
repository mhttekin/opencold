#!/usr/bin/env bash
# Start an interactive codex or claude session with the discovery loop's isolation.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ ! -x .venv/bin/python ]]; then
  echo 'Missing .venv/bin/python. Install the project development environment first.' >&2
  exit 1
fi
exec .venv/bin/python -B -m scripts.agent_session "$@"
