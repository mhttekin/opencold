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
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

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
)
CLAUDE_EXCEPTIONS = ("git push origin main", "gh run list *", "gh run view *", "gh run watch *")


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
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    require(
        result.returncode == 0,
        f"{shlex.join(args)} failed ({result.returncode}): {result.stderr.strip()}",
    )
    return result.stdout.strip()


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


def agent_command(agent: str) -> list[str]:
    if agent == "codex":
        return [
            "codex",
            "-a",
            "never",
            "exec",
            "--sandbox",
            "workspace-write",
            "-c",
            "sandbox_workspace_write.network_access=false",
            "-c",
            "sandbox_workspace_write.writable_roots=[]",
            "--json",
            PROMPT,
        ]
    settings = {
        "permissions": {
            "allow": [
                "Edit(./**)",
                "Write(./**)",
                *(f"Bash({command})" for command in CLAUDE_EXCEPTIONS),
            ],
        },
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "excludedCommands": CLAUDE_EXCEPTIONS,
        },
    }
    return [
        "claude",
        "-p",
        PROMPT,
        "--output-format",
        "json",
        "--permission-mode",
        "dontAsk",
        "--setting-sources",
        "project",
        "--settings",
        json.dumps(settings),
        "--no-chrome",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
    ]


def wait_for_agent(command: list[str], stdout: Path, stderr: Path, timeout: float) -> int:
    with stdout.open("wb") as out, stderr.open("wb") as err:
        with subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=True,
        ) as process:
            try:
                return process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                # Git, hooks and other shell children normally share this process group.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                raise


def record_usage(agent: str, unit: str, duration: float, stdout: Path) -> None:
    keys = ("input_tokens", "output_tokens", "cached_input_tokens", "cache_creation_input_tokens")
    totals = {}
    with stdout.open(encoding="utf-8", errors="replace") as stream:
        records = stream if agent == "codex" else (stream.read(),)
        for record in records:
            try:
                event = json.loads(record)
            except ValueError:
                continue  # An interrupted session can leave a partial record.
            if not isinstance(event, dict) or (
                agent == "codex" and event.get("type") != "turn.completed"
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


def run_agent(agent: str, unit: str, log: Path, timeout_min: int) -> None:
    stdout = log / ("stdout.jsonl" if agent == "codex" else "stdout.json")
    start = time.monotonic()
    try:
        status = wait_for_agent(agent_command(agent), stdout, log / "stderr.log", timeout_min * 60)
    except subprocess.TimeoutExpired as exc:
        raise CheckFailed(f"agent timed out after {timeout_min} minute(s)") from exc
    finally:
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


def verify_session(before: Snapshot, units: list[dict], unit: str, log: Path) -> str:
    on_main()
    head = output("git", "rev-parse", "HEAD")
    parents = output("git", "show", "-s", "--format=%P", head)
    require(
        parents == before.head, "expected exactly one new commit directly on top of starting HEAD"
    )
    synced(head)
    after_units = queue()
    after = snapshot(head, after_units)
    require(after.passes == before.passes + 1, "passes count did not increase by exactly one")
    expected = {entry["id"]: entry["passes"] or entry["id"] == unit for entry in units}
    require(
        {entry["id"]: entry["passes"] for entry in after_units} == expected,
        "passes changed outside the selected unit",
    )
    clean_tree()
    checked(["./scripts/check.sh"], log, "check.sh")
    require(after.golden_hashes == before.golden_hashes, "golden hash changed")
    require(
        after.discovery_lines < before.discovery_lines, "discovery.py line count did not decrease"
    )
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
    require(bool(runs) and runs[0]["headSha"] == head, f"CI run for {head} was not found")
    run_id = str(runs[0]["databaseId"])
    checked(["gh", "run", "watch", run_id, "--exit-status"], log, "CI")
    result = json.loads(output("gh", "run", "view", run_id, "--json", "headSha,conclusion"))
    require(
        result["headSha"] == head and result["conclusion"] == "success",
        "CI did not conclude successfully for HEAD",
    )
    clean_tree()
    on_main()
    require(output("git", "rev-parse", "HEAD") == head, "HEAD changed during verification")
    synced(head)
    return head


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def run_units(args: argparse.Namespace) -> int:
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
            log = LOGS / f"{unit_id}-{stamp}"
            log.mkdir(mode=0o700, parents=True)
            (log / "before.json").write_text(
                json.dumps(asdict(before), indent=2) + "\n", encoding="utf-8"
            )
            print(f"Starting {args.agent} for {unit_id}. Logs: {log}", flush=True)
            run_agent(args.agent, unit_id, log, args.timeout_min)
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
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("codex", "claude"), required=True)
    parser.add_argument("--max-units", type=positive_int, required=True)
    parser.add_argument("--timeout-min", type=positive_int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    os.environ.update(GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1")
    if args.dry_run:
        return run_units(args)
    lock_path = LOGS / "run_units.lock"
    try:
        LOGS.mkdir(exist_ok=True)
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return run_units(args)
    except OSError as exc:
        print(
            f"Stopped before selecting a unit: could not lock {lock_path}: {exc}", file=sys.stderr
        )
        print(
            "Log: none (session not started). Inspect any existing runner and its logs.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
