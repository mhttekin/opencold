"""Exercise the runner with real local Git refs and stub agent/CI commands."""

import csv
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.run_units import wait_for_agent

ROOT = Path(__file__).resolve().parents[1]
PLAN = Path("docs/plans/discovery-split")
PROMPT = (
    'Continue the discovery.py split. Follow "Rules for coding sessions" in '
    "docs/plans/discovery-split/plan.md. One unit only, then stop and report."
    " This is a loop session. Review the unstaged changes, mark the unit done,"
    " and leave all changes unstaged and uncommitted. The runner handles Git writes and CI."
)


def git(repo, *args):
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, stderr=subprocess.PIPE
    ).strip()


def executable(path, script):
    path.write_text(script)
    path.chmod(0o755)


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote))
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Runner Test")
    git(repo, "config", "core.hooksPath", "/dev/null")
    git(repo, "remote", "add", "origin", str(remote))
    files = {
        ".gitignore": ".agent-logs/\n.venv/\n",
        PLAN / "features.json": json.dumps(
            [
                {"id": "01-first", "passes": False, "requires": "golden-v2"},
                {"id": "02-next", "passes": False},
            ]
        ),
        PLAN / "progress.md": "## golden-v2 — done\n",
        "src/opencold/discovery.py": "one\ntwo\nthree\n",
        "tests/fixtures/discover_golden.json": "[]\n",
        "tests/fixtures/discover_golden_v2.json": "{}\n",
    }
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (repo / "scripts").mkdir()
    for name in ("run_units.sh", "run_units.py"):
        shutil.copy2(ROOT / "scripts" / name, repo / "scripts" / name)
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(sys.executable)
    executable(repo / "scripts/check.sh", '#!/bin/sh\necho check.sh ran\nexit "${CHECK_EXIT:-0}"\n')
    git(repo, "add", "--", ".gitignore", "docs", "scripts", "src", "tests")
    git(repo, "commit", "-m", "Initial fixture")
    git(repo, "push", "-u", "origin", "main")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = (
        f"#!{sys.executable}\n"
        + """
import json
import os
import subprocess
import sys
from pathlib import Path

def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()

agent = Path(sys.argv[0]).name
with open(os.environ['STUB_CALLS'], 'a') as calls:
    calls.write(json.dumps([agent, *sys.argv[1:]]) + '\\n')
if agent == 'gh':
    if sys.argv[1:3] == ['run', 'list']:
        head = sys.argv[sys.argv.index('--commit') + 1]
        assert head == git('rev-parse', 'HEAD')
        print(json.dumps([{'databaseId': 123, 'headSha': 'wrong' if os.environ.get('CI_WRONG') else head}]))
    elif sys.argv[1:3] == ['run', 'watch']:
        assert sys.argv[3] == '123' and '--exit-status' in sys.argv
        sys.exit(int(os.environ.get('CI_EXIT', '0')))
    elif sys.argv[1:3] == ['run', 'view']:
        assert sys.argv[3] == '123'
        print(json.dumps({'headSha': git('rev-parse', 'HEAD'),
                          'conclusion': os.environ.get('CI_CONCLUSION', 'success')}))
    else:
        raise AssertionError(sys.argv)
    sys.exit()

mode = os.environ.get('AGENT_RESULT', 'success')
if mode == 'exit':
    sys.exit(7)
features = Path('docs/plans/discovery-split/features.json')
units = json.loads(features.read_text())
pending = [unit for unit in units if not unit['passes']]
if mode != 'no-pass':
    pending[1 if mode == 'wrong-unit' else 0]['passes'] = True
features.write_text(json.dumps(units))
source = Path('src/opencold/discovery.py')
if mode != 'same-size':
    source.write_text('\\n'.join(source.read_text().splitlines()[:-1]) + '\\n')
paths = [str(features), str(source)]
if mode == 'golden':
    golden = Path('tests/fixtures/discover_golden_v2.json')
    golden.write_text('changed\\n')
    paths.append(str(golden))
if mode in ('staged', 'agent-commit'):
    git('add', '--', *paths)
if mode == 'agent-commit':
    git('commit', '-m', 'Fixture unit')
if mode == 'dirty':
    Path('untracked.txt').touch()
usage = {} if mode == 'no-usage' else {'input_tokens': 50, 'output_tokens': 25}
if agent == 'codex':
    print(json.dumps({'type': 'turn.completed', 'usage': usage}))
else:
    print(json.dumps({'type': 'result', 'usage': usage}))
print('diagnostic on stderr', file=sys.stderr)
"""
    )
    for name in ("codex", "claude", "gh"):
        executable(bin_dir / name, stub)
    calls = tmp_path / "calls.jsonl"
    monkeypatch.setenv("STUB_CALLS", str(calls))
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    return repo, calls, remote


def run(repo, agent="codex", *args):
    return subprocess.run(
        ["./scripts/run_units.sh", "--agent", agent, "--max-units", "2", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10,
    )


def calls_from(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.parametrize("agent", ["codex", "claude"])
def test_success_runs_one_session_per_unit_and_logs_usage(checkout, agent):
    repo, calls, _ = checkout
    result = run(repo, agent)
    assert result.returncode == 0, result.stderr
    recorded = calls_from(calls)
    sessions = [call for call in recorded if call[0] == agent]
    assert len(sessions) == 2
    assert [call[1:3] for call in recorded if call[0] == "gh"] == [
        ["run", "list"],
        ["run", "watch"],
        ["run", "view"],
        ["run", "list"],
        ["run", "watch"],
        ["run", "view"],
    ]
    assert all(PROMPT in call for call in sessions)
    if agent == "codex":
        assert all(
            "--json" in call
            and "workspace-write" in call
            and "never" in call
            and "--ignore-rules" in call
            for call in sessions
        )
    else:
        assert all("-p" in call and "json" in call and "dontAsk" in call for call in sessions)
        settings = json.loads(sessions[0][sessions[0].index("--settings") + 1])
        assert settings["sandbox"]["failIfUnavailable"]
        assert not settings["sandbox"]["allowUnsandboxedCommands"]
        assert settings["sandbox"]["excludedCommands"] == []
        assert settings["sandbox"]["network"]["allowedDomains"] == []
        assert settings["sandbox"]["filesystem"]["denyWrite"] == [str(repo / ".git")]
    with (repo / ".agent-logs/usage.csv").open() as stream:
        usage = list(csv.DictReader(stream))
    assert [
        (row["unit"], row["agent"], row["input_tokens"], row["output_tokens"]) for row in usage
    ] == [
        ("01-first", agent, "50", "25"),
        ("02-next", agent, "50", "25"),
    ]
    log = next((repo / ".agent-logs").glob("01-first-*"))
    stdout = log / ("stdout.jsonl" if agent == "codex" else "stdout.json")
    assert json.loads(stdout.read_text())["usage"]["input_tokens"] == 50
    assert "diagnostic on stderr" in (log / "stderr.log").read_text()
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "log", "-2", "--format=%s").splitlines() == [
        "Split discovery: 02-next",
        "Split discovery: 01-first",
    ]


def test_dry_run_does_not_launch_or_write_logs(checkout):
    repo, calls, _ = checkout
    result = run(repo, "codex", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "01-first" in result.stdout
    assert not calls.exists()
    assert not (repo / ".agent-logs").exists()


@pytest.mark.parametrize(
    "case,diagnostic",
    [
        ("dirty", "clean tree"),
        ("wrong-branch", "branch main"),
        ("behind-remote", "remote main"),
        ("local-ahead", "origin/main"),
        ("requires", "golden-v2"),
    ],
)
def test_precondition_failure_does_not_launch(checkout, tmp_path, case, diagnostic):
    repo, calls, remote = checkout
    if case == "dirty":
        (repo / "untracked").touch()
    elif case == "wrong-branch":
        git(repo, "switch", "-c", "other")
    elif case == "behind-remote":
        sibling = tmp_path / "sibling"
        git(tmp_path, "clone", "-b", "main", str(remote), str(sibling))
        git(
            sibling,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-m",
            "Advance remote",
        )
        git(sibling, "push", "origin", "main")
        assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")
    elif case == "local-ahead":
        git(repo, "commit", "--allow-empty", "-m", "Local only")
    else:
        (repo / PLAN / "progress.md").write_text("## golden-v2 — pending\n")
        git(repo, "add", str(PLAN / "progress.md"))
        git(repo, "commit", "-m", "Prerequisite pending")
        git(repo, "push", "origin", "main")
    result = run(repo)
    assert result.returncode != 0
    assert "01-first" in result.stderr and diagnostic in result.stderr
    assert "Inspect" in result.stderr
    assert not calls.exists()


@pytest.mark.parametrize(
    "mode,diagnostic",
    [
        ("exit", "agent exit 7"),
        ("agent-commit", "leave HEAD unchanged"),
        ("staged", "leave all changes unstaged"),
        ("no-pass", "passes count"),
        ("wrong-unit", "selected unit"),
        ("dirty", "unexpected changed paths"),
        ("golden", "golden hash"),
        ("same-size", "line count"),
        ("check", "check.sh"),
        ("ci", "CI"),
        ("ci-skipped", "CI did not conclude successfully"),
        ("ci-wrong", "CI run for"),
    ],
)
def test_postcondition_failure_stops_without_retry(checkout, monkeypatch, mode, diagnostic):
    repo, calls, _ = checkout
    monkeypatch.setenv("AGENT_RESULT", mode)
    if mode == "check":
        monkeypatch.setenv("CHECK_EXIT", "1")
    if mode == "ci":
        monkeypatch.setenv("CI_EXIT", "1")
    if mode == "ci-skipped":
        monkeypatch.setenv("CI_CONCLUSION", "skipped")
    if mode == "ci-wrong":
        monkeypatch.setenv("CI_WRONG", "1")
    head = git(repo, "rev-parse", "HEAD")
    result = run(repo)
    assert result.returncode != 0
    assert diagnostic in result.stderr and "01-first" in result.stderr
    assert "Inspect" in result.stderr
    assert "git stash -u" in result.stderr
    log = next((repo / ".agent-logs").glob("01-first-*"))
    assert log.name in result.stderr
    assert [call[0] for call in calls_from(calls)].count("codex") == 1
    if not mode.startswith("ci"):
        assert git(repo, "rev-parse", "origin/main") == head


def test_missing_usage_does_not_create_csv(checkout, monkeypatch):
    repo, _, _ = checkout
    monkeypatch.setenv("AGENT_RESULT", "no-usage")
    result = run(repo)
    assert result.returncode == 0, result.stderr
    assert not (repo / ".agent-logs/usage.csv").exists()


def test_agent_timeout_preserves_output_and_stops_child_processes(tmp_path):
    marker = tmp_path / "child-finished"
    stdout = tmp_path / "stdout.jsonl"
    child = f"import time; time.sleep(1); open({str(marker)!r}, 'w').close()"
    parent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        "print('started', flush=True); time.sleep(10)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        wait_for_agent([sys.executable, "-c", parent], stdout, tmp_path / "stderr.log", 0.5)
    assert stdout.read_text() == "started\n"
    time.sleep(1)
    assert not marker.exists()
