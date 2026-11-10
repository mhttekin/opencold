#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
file=$("$root/.venv/bin/python" -c 'import json,sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))')
exec "$root/scripts/fix-file.sh" "$file"
