"""Discovery queue state, Git operations, and verification gates."""

import hashlib
import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
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
FEATURES = PLAN / "features.json"
PROGRESS = PLAN / "progress.md"
RATCHET = Path("tests/test_invariants.py")
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
    units = json.loads(FEATURES.read_text(encoding="utf-8"))
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
        headings = PROGRESS.read_text(encoding="utf-8").splitlines()
        require(
            f"## {name} — done" in headings,
            f"prerequisite {name} is not marked done in {PLAN / 'progress.md'}",
        )


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
    require(output("git", "rev-parse", "HEAD") == head, "unit must leave HEAD unchanged")
    status = output("git", "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all")
    changes = status.split("\0")[:-1]
    require(all(entry[0] in " ?" for entry in changes), "unit must leave all changes unstaged")
    paths = [entry[3:] for entry in changes]
    outside = [path for path in paths if not path.startswith(UNIT_PATHS)]
    require(not outside, f"unexpected changed paths: {outside!r}")
    return paths


def verify_unit(before: Snapshot, units: list[dict], unit: str, log: Path) -> list[str]:
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
    return paths


def commit_unit(
    before: Snapshot, unit: str, mode: str, paths: list[str], log: Path, green: str
) -> str:
    suffix = " (tool)" if mode == "tool" else ""
    message = ["-m", f"Split discovery: {unit}{suffix}"]
    if mode == "agent":
        notes = log / "commit-body.txt"
        require(not notes.is_symlink(), "commit body must be a regular file")
        if notes.is_file() and (body := notes.read_text(encoding="utf-8").strip()):
            message.extend(("-m", body))
    synced(green)
    checked(["git", "--literal-pathspecs", "add", "--", *paths], log, "git add")
    checked(["git", "commit", *message], log, "git commit")
    head = output("git", "rev-parse", "HEAD")
    require(
        output("git", "show", "-s", "--format=%P", head) == before.head, "expected one new commit"
    )
    clean_tree()
    return head


def publish(head: str, green: str, log: Path) -> None:
    clean_tree()
    on_main()
    require(output("git", "rev-parse", "HEAD") == head, "HEAD changed before push")
    synced(green)
    checked(["git", "push", "origin", "main"], log, "git push")
    synced(head)
    verify_ci(head, log)
    clean_tree()
    on_main()
    require(output("git", "rev-parse", "HEAD") == head, "HEAD changed during verification")
    synced(head)


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


def restore_unit(head: str, log: Path) -> None:
    on_main()
    require(output("git", "rev-parse", "HEAD") == head, "HEAD changed during the tool attempt")
    checked(
        ["git", "restore", f"--source={head}", "--staged", "--worktree", "--", "."],
        log,
        "restore tracked paths",
    )
    untracked = output("git", "ls-files", "--others", "--exclude-standard", "-z").split("\0")[:-1]
    if untracked:
        checked(
            ["git", "--literal-pathspecs", "clean", "-f", "--", *untracked],
            log,
            "remove paths created by the tool attempt",
        )
    clean_tree()


def lower_ratchet(before: int, after: int) -> bool:
    text = RATCHET.read_text(encoding="utf-8")
    pattern = r'^    "discovery\.py": (\d+),\n'
    entries = re.findall(pattern, text, re.MULTILINE)
    if before <= 400 and not entries:
        return False
    require(entries == [str(before)], "discovery.py ratchet differs from its pre-unit line count")
    replacement = f'    "discovery.py": {after},\n' if after > 400 else ""
    RATCHET.write_text(re.sub(pattern, replacement, text, flags=re.MULTILINE), encoding="utf-8")
    return True


def verify_tool_unit(before: Snapshot, units: list[dict], unit: dict, log: Path) -> list[str]:
    target = Path(unit["target_module"])
    expected = {str(SOURCE), str(target)}
    require(
        set(unit_changes(before.head)) == expected, "unexpected changed paths from move_defs.py"
    )
    require(target.is_file() and not target.is_symlink(), "expected a new regular target module")
    after_lines = len(SOURCE.read_bytes().splitlines())
    require(after_lines < before.discovery_lines, "discovery.py line count did not decrease")
    if lower_ratchet(before.discovery_lines, after_lines):
        expected.add(str(RATCHET))
    updated = [dict(entry, passes=True) if entry["id"] == unit["id"] else entry for entry in units]
    FEATURES.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    progress = PROGRESS.read_text(encoding="utf-8").rstrip("\n")
    PROGRESS.write_text(
        f"{progress}\n\n- {unit['id']} mode=tool, {before.discovery_lines}→{after_lines} lines\n",
        encoding="utf-8",
    )
    paths = verify_unit(before, units, unit["id"], log)
    require(set(paths) == expected | {str(FEATURES), str(PROGRESS)}, "unexpected tool-mode paths")
    return paths
