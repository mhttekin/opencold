"""Run discovery splits with the move tool and fall back to agent sessions."""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import shlex
import subprocess
import sys
import time
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from scripts.unit_agent import (
    PREFLIGHT_PROMPT,
    agent_command,
    agent_environment,
    claude_git_dirs,
    verify_preflight,
    wait_for_agent,
)
from scripts.unit_checks import (
    PLAN,
    CheckFailed,
    Snapshot,
    clean_tree,
    commit_unit,
    on_main,
    output,
    prerequisite,
    publish,
    queue,
    require,
    restore_unit,
    snapshot,
    synced,
    verify_tool_unit,
    verify_unit,
)
from scripts.unit_context import compact_progress, write_brief
from scripts.unit_usage import record_agent_usage, record_tool_usage

LOGS = Path(".agent-logs")
PROMPT = (
    "Continue the discovery.py split. Read {brief} first. "
    "It contains the selected unit, tool refusal, locations, relevant plan rules and recent progress. "
    "One unit only. Leave changes unstaged and uncommitted; the runner handles Git writes and CI."
)


def launch_agent(agent: str, prompt: str, log: Path, timeout_min: int, env: dict[str, str]) -> int:
    git_dirs = claude_git_dirs() if agent == "claude" else []
    return wait_for_agent(
        agent_command(agent, prompt, git_dirs),
        log / "stdout.jsonl",
        log / "stderr.log",
        timeout_min * 60,
        env=dict(env, OPENCOLD_UNIT_NOTES=str((log / "commit-body.txt").resolve())),
    )


def agent_preflight(agent: str, timeout_min: int, env: dict[str, str], log: Path) -> None:
    log.mkdir(mode=0o700, parents=True)
    print(f"Running {agent} preflight. Logs: {log}", flush=True)
    try:
        status = launch_agent(agent, PREFLIGHT_PROMPT, log, timeout_min, env)
        require(status == 0, f"agent preflight exit {status}")
        verify_preflight(agent, log / "stdout.jsonl", env)
    except subprocess.TimeoutExpired as exc:
        raise CheckFailed(f"agent preflight timed out after {timeout_min} minute(s)") from exc
    print(f"{agent} preflight passed (pwd and repository review skill only).", flush=True)


def run_agent(agent: str, unit: str, log: Path, timeout_min: int, env: dict[str, str]) -> None:
    start = time.monotonic()
    try:
        status = launch_agent(agent, PROMPT.format(brief=log / "brief.md"), log, timeout_min, env)
    except subprocess.TimeoutExpired as exc:
        raise CheckFailed(f"agent timed out after {timeout_min} minute(s)") from exc
    finally:
        stdout = log / "stdout.jsonl"
        if stdout.is_file():
            record_agent_usage(LOGS / "usage.csv", agent, unit, time.monotonic() - start, stdout)
    require(status == 0, f"agent exit {status}")


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


RUN_ERRORS = (CheckFailed, OSError, ValueError, KeyError, TypeError)


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def try_tool(before: Snapshot, units: list[dict], unit: dict, log: Path) -> list[str] | None:
    try:
        result = subprocess.run(
            [sys.executable, "scripts/move_defs.py", unit["id"]],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        with (log / "checks.log").open("a", encoding="utf-8") as stream:
            stream.write(f"$ move_defs.py {unit['id']}\n{result.stdout}{result.stderr}")
        if result.returncode:
            try:
                reason = json.loads(result.stderr)
                require(
                    isinstance(reason, dict)
                    and all(
                        isinstance(reason.get(key), str) and reason[key]
                        for key in ("category", "detail")
                    ),
                    "invalid mover refusal record",
                )
            except (ValueError, CheckFailed):
                reason = {
                    "category": "tool_process_failed",
                    "detail": f"move_defs.py exit {result.returncode}: {result.stderr.strip()}",
                }
            (log / "refusal.json").write_text(json.dumps(reason) + "\n", encoding="utf-8")
            raise CheckFailed(reason["detail"])
        return verify_tool_unit(before, units, unit, log)
    except RUN_ERRORS as exc:
        refusal_path = log / "refusal.json"
        reason = (
            json.loads(refusal_path.read_text())
            if refusal_path.exists()
            else {"category": "postcheck_failed", "detail": str(exc)}
        )
        refusal_path.write_text(json.dumps(reason) + "\n", encoding="utf-8")
        with (LOGS / "refusals.csv").open("a", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=("timestamp", "unit", "category", "detail", "log")
            )
            if stream.tell() == 0:
                writer.writeheader()
            writer.writerow(
                dict(
                    timestamp=timestamp(),
                    unit=unit["id"],
                    category=reason["category"],
                    detail=reason["detail"],
                    log=str(log),
                )
            )
        restore_unit(before.head, log)
        write_brief(unit, reason, log)
        print(f"{unit['id']} tool attempt restored ({exc}). Falling back to agent.", flush=True)
        return None
    except KeyboardInterrupt:
        restore_unit(before.head, log)
        raise


def run_units(args: argparse.Namespace, stack: ExitStack) -> int:
    env = None
    head = green = None
    pending = 0
    log = None
    last_log = None
    unit_id = "(unknown)"
    try:
        for _ in range(args.max_units):
            log = None
            units = queue()
            unit = next((entry for entry in units if not entry["passes"]), None)
            unit_id = unit["id"] if unit else "(queue complete)"
            clean_tree()
            on_main()
            current = output("git", "rev-parse", "HEAD")
            if head is None:
                head = green = current
            require(current == head, "HEAD changed between units")
            synced(green)
            if unit is None:
                print("All discovery split units are marked done.")
                break
            before = snapshot(head, units)
            print(f"{unit_id} preflight: {json.dumps(asdict(before))}", flush=True)
            prerequisite(unit)
            if args.dry_run:
                print(
                    f"Dry run: would try move_defs.py for {unit_id}, then {args.agent} if needed."
                )
                return 0

            log = LOGS / f"{unit_id}-{timestamp()}"
            log.mkdir(mode=0o700, parents=True)
            (log / "before.json").write_text(
                json.dumps(asdict(before), indent=2) + "\n", encoding="utf-8"
            )
            start = time.monotonic()
            paths = try_tool(before, units, unit, log)
            mode = "tool"
            if paths is None:
                mode = "agent"
                if env is None:
                    env = stack.enter_context(agent_environment(args.agent))
                    unit_log, log = log, LOGS / f"preflight-{args.agent}-{timestamp()}"
                    agent_preflight(args.agent, args.timeout_min, env, log)
                    clean_tree()
                    on_main()
                    require(output("git", "rev-parse", "HEAD") == head, "preflight changed HEAD")
                    log = unit_log
                print(f"Starting {args.agent} for {unit_id}. Logs: {log}", flush=True)
                run_agent(args.agent, unit_id, log, args.timeout_min, env)
                paths = verify_unit(before, units, unit_id, log)
            duration = time.monotonic() - start
            paths = sorted(set(paths) | set(compact_progress()))
            head = commit_unit(before, unit_id, mode, paths, log, green)
            pending += 1
            if mode == "tool":
                record_tool_usage(LOGS / "usage.csv", unit_id, duration)
            print(f"{unit_id} committed at {head} (mode={mode}). Logs: {log}", flush=True)
            if pending == args.push_every:
                publish(head, green, log)
                green, pending = head, 0
            last_log = log
        if pending:
            log = last_log
            publish(head, green, log)
    except RUN_ERRORS + (KeyboardInterrupt,) as exc:
        print(f"Stopped on {unit_id}: {exc or 'interrupted'}", file=sys.stderr)
        if head != green:
            print(f"Commits since last green push: {green}..{head}", file=sys.stderr)
        if log is None:
            print(
                f"Log: none (session not started). Inspect git status --short --branch and {PLAN}.",
                file=sys.stderr,
            )
        else:
            print(
                f"Log: {log}. Inspect with ls {shlex.quote(str(log))} and cat the relevant log file.",
                file=sys.stderr,
            )
        print("Reset uncommitted changes with git stash -u after inspection.", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("codex", "claude"), required=True)
    parser.add_argument("--max-units", type=positive_int, required=True)
    parser.add_argument("--push-every", type=positive_int, default=1)
    parser.add_argument("--timeout-min", type=positive_int, default=20)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    os.environ.update(GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1")
    if args.dry_run:
        with ExitStack() as stack:
            return run_units(args, stack)
    lock_path = LOGS / "run_units.lock"
    try:
        LOGS.mkdir(exist_ok=True)
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not args.preflight_only:
                with ExitStack() as stack:
                    return run_units(args, stack)
            log = LOGS / f"preflight-{args.agent}-{timestamp()}"
            try:
                with agent_environment(args.agent) as env:
                    agent_preflight(args.agent, args.timeout_min, env, log)
            except RUN_ERRORS + (KeyboardInterrupt,) as exc:
                print(
                    f"Agent preflight failed: {exc or 'interrupted'}. Logs: {log}", file=sys.stderr
                )
                return 1
            return 0
    except OSError as exc:
        print(
            f"Stopped before selecting a unit: could not initialize the runner: {exc}",
            file=sys.stderr,
        )
        print(
            "Log: none (session not started). Inspect any existing runner and its logs. "
            "Reset uncommitted changes with git stash -u after inspection.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
