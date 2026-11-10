#!/usr/bin/env bash
f="${1:-}"
[[ "$f" == *.py && -f "$f" ]] || exit 0
ruff format -q "$f"
ruff check --fix -q "$f" >/dev/null
out=$(ruff check "$f" 2>&1) || { echo "$out" >&2; exit 2; }
