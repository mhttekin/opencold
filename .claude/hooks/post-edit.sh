#!/usr/bin/env bash
f=$(python -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))')
exec "$CLAUDE_PROJECT_DIR/scripts/fix-file.sh" "$f"
