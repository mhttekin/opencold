#!/usr/bin/env bash
# Shared gate: stdout stays empty; failures provide a bounded reason on stderr.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
mkdir -p .agent-logs
log=$(mktemp "$PWD/.agent-logs/check.XXXXXXXX")
if ./scripts/check.sh >"$log" 2>&1; then
  exit 0
fi
printf 'Checks failed. Fix the failures and rerun ./scripts/check.sh. Log: %s\n' "$log" >&2
tail -n 30 "$log" >&2
exit 2
