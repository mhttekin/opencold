#!/usr/bin/env bash
# Stop stdout contract: https://learn.chatgpt.com/docs/hooks#stop
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
if reason=$(./scripts/agent-check.sh 2>&1); then
  exit 0
fi
"$PWD/.venv/bin/python" -c 'import json, sys; print(json.dumps({"decision": "block", "reason": sys.argv[1]}))' "$reason"
