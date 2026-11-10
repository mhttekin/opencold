#!/usr/bin/env bash
# Stop stdout contract: https://learn.chatgpt.com/docs/hooks#stop
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
exec "$PWD/.venv/bin/python" "$PWD/scripts/codex_stop.py"
