"""Codex Stop protocol: allow only one automatic check-failure continuation."""

import json
import re
import subprocess
import sys


def stop_response(stop_input: str, returncode: int, reason: str) -> dict:
    """Return a Stop response; an absent active flag means the first attempt."""
    event = json.loads(stop_input)
    if returncode == 0:
        return {}
    if event.get("stop_hook_active", False):
        log = re.search(r"\.agent-logs/[^\s]+", reason)
        warning = (
            f"checks still failing, see {log.group()}" if log else f"checks still failing: {reason}"
        )
        return {"systemMessage": warning}
    return {"decision": "block", "reason": reason}


def main() -> None:
    stop_input = sys.stdin.read()
    result = subprocess.run(
        ["./scripts/agent-check.sh"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(json.dumps(stop_response(stop_input, result.returncode, result.stdout)))


if __name__ == "__main__":
    main()
