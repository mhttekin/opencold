#!/usr/bin/env bash
f="${1:-}"
[[ "$f" == *.py && -f "$f" ]] || exit 0
root="$(git rev-parse --show-toplevel 2>/dev/null)"
if [[ -n "$root" && -d "$root/.venv/bin" ]]; then
  export PATH="$root/.venv/bin:$PATH"
fi
ruff format -q "$f"
ruff check --fix -q "$f" >/dev/null
out=$(ruff check "$f" 2>&1) || { echo "$out" >&2; exit 2; }
