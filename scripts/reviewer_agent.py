"""CLI adapters for fresh, read-only reviewer sessions; no grading policy here."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

AGENTS = ("claude", "codex")


def selected_agent() -> str:
    agent = os.environ.get("AGENT_CLI", "claude")
    if agent not in AGENTS:
        raise ValueError(f"Unsupported AGENT_CLI={agent!r}; choose claude or codex")
    return agent


def command(agent: str, prompt: str) -> list[str]:
    if agent == "claude":
        return [
            "claude",
            "-p",
            prompt,
            "--allowedTools",
            "Read,Grep,Glob,Bash(git diff:*),Bash(git log:*),Bash(git show:*)",
            "--disallowedTools",
            "Edit,Write,NotebookEdit,WebFetch,WebSearch,Agent,Task",
            "--output-format",
            "json",
        ]
    if agent == "codex":
        # A reviewer must not run the workspace's mutating check/format Stop hook.
        return [
            "codex",
            "-a",
            "never",
            "exec",
            "--sandbox",
            "read-only",
            "-c",
            "hooks.Stop=[]",
            "--json",
            prompt,
        ]
    raise ValueError(f"Unsupported reviewer agent: {agent}")


def decode(agent: str, stdout: str) -> tuple[str, dict]:
    """Normalize final review and supplied usage; missing numbers stay unavailable."""
    usage = {"input_tokens": None, "output_tokens": None, "cost_usd": None}
    if agent == "claude":
        data = json.loads(stdout)
        if data.get("is_error"):
            raise ValueError("Reviewer reported an error")
        supplied = data.get("usage", {})
        usage.update({key: supplied.get(key) for key in ("input_tokens", "output_tokens")})
        usage["cost_usd"] = data.get("total_cost_usd")
        return data.get("result", ""), usage
    messages = []
    completed = False
    for line in stdout.splitlines():
        event = json.loads(line)
        if event.get("type") in ("turn.failed", "error"):
            raise ValueError("Reviewer reported an error")
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                messages.append(item.get("text", ""))
        if event.get("type") == "turn.completed":
            completed = True
            supplied = event.get("usage", {})
            usage.update({key: supplied.get(key) for key in ("input_tokens", "output_tokens")})
    if not completed:
        raise ValueError("Reviewer turn did not complete")
    return "\n".join(messages), usage


def run(agent: str, prompt: str, root: Path, timeout: int) -> dict:
    env = dict(os.environ)
    if agent == "claude":
        # Prefer the user's CLI login over an application API key.
        env.pop("ANTHROPIC_API_KEY", None)
    proc = subprocess.run(
        command(agent, prompt),
        cwd=root,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    try:
        text, usage = decode(agent, proc.stdout)
    except (ValueError, TypeError, AttributeError):
        text, usage = "[invalid reviewer output]", {}
    # A failed invocation must never count as a valid verdict.
    error = proc.returncode != 0 or text == "[invalid reviewer output]"
    return {
        "text": text,
        "usage": usage,
        "error": error,
        "raw": proc.stdout + ("\n[stderr]\n" + proc.stderr if proc.stderr else ""),
    }
