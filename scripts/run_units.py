"""Run the discovery split queue one verified agent session at a time."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from scripts.unit_agent import (
    PREFLIGHT_PROMPT,
    agent_command,
    agent_environment,
    verify_preflight,
    wait_for_agent,
)

PLAN = Path("docs/plans/discovery-split")
SOURCE = Path("src/opencold/discovery.py")
GOLDENS = tuple(
    Path("tests/fixtures") / name
    for name in (
        "discover_golden.json",
        "discover_golden_v2.json",
    )
)
LOGS = Path(".agent-logs")
PROMPT = (
    'Continue the discovery.py split. Follow "Rules for coding sessions" in '
    "docs/plans/discovery-split/plan.md. One unit only, then stop and report."
    " This is a loop session. Review the unstaged changes, mark the unit done,"
    " and leave all changes unstaged and uncommitted. The runner handles Git writes and CI."
)
UNIT_PATHS = ("src/opencold/", "tests/", "docs/plans/discovery-split/")


class CheckFailed(Exception):
    """A session must stop for operator inspection."""


@dataclass(frozen=True)
class Snapshot:
    head: str
    passes: int
    discovery_lines: int
    golden_hashes: dict[str, str]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def output(*args: str) -> str:
    result = subprocess.run(
        args, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="surrogateescape"
    )
    require(
        result.returncode == 0,
        f"{shlex.join(args)} failed ({result.returncode}): {result.stderr.strip()}",
    )
    return result.stdout.rstrip("\n")


def clean_tree() -> None:
    require(
        not output("git", "status", "--porcelain", "--untracked-files=all"),
        "clean tree check failed",
    )


def on_main() -> None:
    require(output("git", "branch", "--show-current") == "main", "branch main check failed")


def synced(head: str) -> None:
    require(
        head == output("git", "rev-parse", "refs/remotes/origin/main"),
        "HEAD differs from origin/main",
    )
    tip = output("git", "ls-remote", "--exit-code", "origin", "refs/heads/main").split()
    require(tip == [head, "refs/heads/main"], "HEAD differs from the live remote main tip")


def queue() -> list[dict]:
    units = json.loads((PLAN / "features.json").read_text(encoding="utf-8"))
    require(isinstance(units, list), "features.json must contain a unit list")
    ids = set()
    for unit in units:
        require(
            isinstance(unit, dict)
            and isinstance(unit.get("id"), str)
            and re.fullmatch(r"[a-zA-Z0-9_-]+", unit["id"]) is not None
            and type(unit.get("passes")) is bool,
            "features.json contains an invalid unit id or passes flag",
        )
        require(unit["id"] not in ids, f"duplicate unit id {unit['id']}")
        ids.add(unit["id"])
    return units


def snapshot(head: str, units: list[dict]) -> Snapshot:
    return Snapshot(
        head,
        sum(unit["passes"] for unit in units),
        len(SOURCE.read_bytes().splitlines()),
        {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in GOLDENS},
    )


def prerequisite(unit: dict) -> None:
    if "requires" in unit:
        name = unit["requires"]
        require(isinstance(name, str) and bool(name), "invalid requires value in features.json")
        headings = (PLAN / "progress.md").read_text(encoding="utf-8").splitlines()
        require(
            f"## {name} — done" in headings,
            f"prerequisite {name} is not marked done in {PLAN / 'progress.md'}",
        )


def record_usage(agent: str, unit: str, duration: float, stdout: Path) -> None:
    keys = ("input_tokens", "output_tokens", "cached_input_tokens", "cache_creation_input_tokens")
    totals = {}
    with stdout.open(encoding="utf-8", errors="replace") as stream:
        for record in stream:
            try:
                event = json.loads(record)
            except ValueError:
                continue  # An interrupted session can leave a partial record.
            if not isinstance(event, dict) or (
                event.get("type") != ("turn.completed" if agent == "codex" else "result")
            ):
                continue
            usage = event.get("usage")
            if isinstance(usage, dict):
                if agent == "claude":
                    usage["cached_input_tokens"] = usage.get("cache_read_input_tokens")
                for key in keys:
                    value = usage.get(key)
                    if type(value) is int and value >= 0:
                        totals[key] = totals.get(key, 0) + value
    if totals:
        with (LOGS / "usage.csv").open("a+", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            if stream.tell() == 0:
                writer.writerow(("unit", "agent", "duration_seconds", *keys))
            writer.writerow(
                (unit, agent, f"{duration:.3f}", *(totals.get(key, "") for key in keys))
            )


def launch_agent(agent: str, prompt: str, log: Path, timeout_min: int, env: dict[str, str]) -> int:
    git_dirs = []
    if agent == "claude":
        git_dirs = output(
            "git", "rev-parse", "--path-format=absolute", "--git-common-dir", "--absolute-git-dir"
        ).splitlines()
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
        status = launch_agent(agent, PROMPT, log, timeout_min, env)
    except subprocess.TimeoutExpired as exc:
        raise CheckFailed(f"agent timed out after {timeout_min} minute(s)") from exc
    finally:
        stdout = log / "stdout.jsonl"
        if stdout.is_file():
            record_usage(agent, unit, time.monotonic() - start, stdout)
    require(status == 0, f"agent exit {status}")


def checked(command: list[str], log: Path, label: str) -> None:
    with (log / "checks.log").open("ab") as stream:
        stream.write(f"$ {shlex.join(command)}\n".encode())
        stream.flush()
        status = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT
        ).returncode
    require(status == 0, f"{label} failed (exit {status})")


def unit_changes(head: str) -> list[str]:
    on_main()
    require(output("git", "rev-parse", "HEAD") == head, "agent must leave HEAD unchanged")
    status = output("git", "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all")
    changes = status.split("\0")[:-1]
    require(all(entry[0] in " ?" for entry in changes), "agent must leave all changes unstaged")
    paths = [entry[3:] for entry in changes]
    outside = [path for path in paths if not path.startswith(UNIT_PATHS)]
    require(not outside, f"unexpected changed paths: {outside!r}")
    return paths


def verify_session(before: Snapshot, units: list[dict], unit: str, log: Path) -> str:
    unit_changes(before.head)
    checked(["./scripts/check.sh"], log, "check.sh")
    paths = unit_changes(before.head)
    after_units = queue()
    after = snapshot(before.head, after_units)
    require(after.passes == before.passes + 1, "passes count did not increase by exactly one")
    expected = {entry["id"]: entry["passes"] or entry["id"] == unit for entry in units}
    require(
        {entry["id"]: entry["passes"] for entry in after_units} == expected,
        "passes changed outside the selected unit",
    )
    require(after.golden_hashes == before.golden_hashes, "golden hash changed")
    require(
        after.discovery_lines < before.discovery_lines, "discovery.py line count did not decrease"
    )
    message = ["-m", f"Split discovery: {unit}"]
    notes = log / "commit-body.txt"
    require(not notes.is_symlink(), "commit body must be a regular file")
    if notes.is_file() and (body := notes.read_text(encoding="utf-8").strip()):
        message.extend(("-m", body))
    synced(before.head)
    checked(["git", "--literal-pathspecs", "add", "--", *paths], log, "git add")
    checked(["git", "commit", *message], log, "git commit")
    head = output("git", "rev-parse", "HEAD")
    require(
        output("git", "show", "-s", "--format=%P", head) == before.head, "expected one new commit"
    )
    clean_tree()
    checked(["git", "push", "origin", "main"], log, "git push")
    synced(head)
    verify_ci(head, log)
    clean_tree()
    on_main()
    require(output("git", "rev-parse", "HEAD") == head, "HEAD changed during verification")
    synced(head)
    return head


def verify_ci(head: str, log: Path) -> None:
    deadline = time.monotonic() + 45
    while True:
        runs = json.loads(
            output(
                "gh",
                "run",
                "list",
                "--workflow",
                "ci.yml",
                "--branch",
                "main",
                "--event",
                "push",
                "--commit",
                head,
                "--limit",
                "1",
                "--json",
                "databaseId,headSha",
            )
        )
        if runs:
            break
        require(time.monotonic() < deadline, f"CI run for {head} was not found")
        time.sleep(3)
    require(runs[0]["headSha"] == head, f"CI run for {head} was not found")
    run_id = str(runs[0]["databaseId"])
    checked(["gh", "run", "watch", run_id, "--exit-status"], log, "CI")
    result = json.loads(output("gh", "run", "view", run_id, "--json", "headSha,conclusion"))
    require(
        result["headSha"] == head and result["conclusion"] == "success",
        "CI did not conclude successfully for HEAD",
    )


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def run_units(args: argparse.Namespace, env: dict[str, str] | None = None) -> int:
    preflight_done = False
    for _ in range(args.max_units):
        unit_id = "(unknown)"
        log = None
        try:
            units = queue()
            unit = next((entry for entry in units if not entry["passes"]), None)
            unit_id = unit["id"] if unit else "(queue complete)"
            clean_tree()
            on_main()
            head = output("git", "rev-parse", "HEAD")
            synced(head)
            if unit is None:
                print("All discovery split units are marked done.")
                break
            before = snapshot(head, units)
            print(f"{unit_id} preflight: {json.dumps(asdict(before))}", flush=True)
            prerequisite(unit)
            if args.dry_run:
                print(
                    f"Dry run: would start {args.agent} for {unit_id} (timeout {args.timeout_min} minutes)."
                )
                break
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            if not preflight_done:
                assert env is not None
                log = LOGS / f"preflight-{args.agent}-{stamp}"
                agent_preflight(args.agent, args.timeout_min, env, log)
                clean_tree()
                on_main()
                require(output("git", "rev-parse", "HEAD") == head, "preflight changed HEAD")
                preflight_done = True
            log = LOGS / f"{unit_id}-{stamp}"
            log.mkdir(mode=0o700, parents=True)
            (log / "before.json").write_text(
                json.dumps(asdict(before), indent=2) + "\n", encoding="utf-8"
            )
            print(f"Starting {args.agent} for {unit_id}. Logs: {log}", flush=True)
            run_agent(args.agent, unit_id, log, args.timeout_min, env)
            head = verify_session(before, units, unit_id, log)
            print(f"{unit_id} verified at {head}. Logs: {log}", flush=True)
        except (CheckFailed, OSError, ValueError, KeyError, TypeError, KeyboardInterrupt) as exc:
            print(f"Stopped on {unit_id}: {exc or 'interrupted'}", file=sys.stderr)
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
    parser.add_argument("--timeout-min", type=positive_int, default=20)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    os.environ.update(GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1")
    if args.dry_run:
        return run_units(args)
    lock_path = LOGS / "run_units.lock"
    try:
        LOGS.mkdir(exist_ok=True)
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with agent_environment(args.agent) as env:
                if not args.preflight_only:
                    return run_units(args, env)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
                log = LOGS / f"preflight-{args.agent}-{stamp}"
                try:
                    agent_preflight(args.agent, args.timeout_min, env, log)
                except (
                    CheckFailed,
                    OSError,
                    ValueError,
                    KeyError,
                    TypeError,
                    KeyboardInterrupt,
                ) as exc:
                    print(
                        f"Agent preflight failed: {exc or 'interrupted'}. Logs: {log}",
                        file=sys.stderr,
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
