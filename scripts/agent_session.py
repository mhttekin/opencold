"""Interactive agent session with the same isolation as scripts/run_units.sh sessions."""

import signal
import subprocess
import sys

from scripts.unit_agent import agent_environment, interactive_command

USAGE = "usage: scripts/agent.sh codex|claude [args...]"


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("codex", "claude"):
        print(USAGE, file=sys.stderr)
        return 2
    agent, args = argv[0], argv[1:]
    with agent_environment(agent) as env:
        process = subprocess.Popen(interactive_command(agent, args), env=env)
        # Ignore Ctrl-C only after the start, so the CLI does not inherit SIG_IGN; the
        # wrapper stays alive to remove the scoped home when the CLI exits.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        return process.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
