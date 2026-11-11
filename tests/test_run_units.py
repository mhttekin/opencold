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
    " The runner attempted move_defs.py and restored the checkout. This is an agent-mode loop session."
    " Run the review skill on the unstaged changes, mark the unit done,"
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
        ".agents/skills/review/SKILL.md": "---\nname: review\n---\n",
        PLAN / "features.json": json.dumps(
            [
                {
                    "id": "01-first",
                    "passes": False,
                    "requires": "golden-v2",
                    "target_module": "src/opencold/discovery_first.py",
                },
                {
                    "id": "02-next",
                    "passes": False,
                    "target_module": "src/opencold/discovery_next.py",
                },
            ]
        ),
        PLAN / "progress.md": "## golden-v2 — done\n",
        "src/opencold/discovery.py": "one\ntwo\nthree\n" + "# filler\n" * 402,
        "tests/test_invariants.py": 'GRANDFATHERED = {\n    "discovery.py": 405,\n}\n',
        "tests/fixtures/discover_golden.json": "[]\n",
        "tests/fixtures/discover_golden_v2.json": "{}\n",
    }
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (repo / "scripts").mkdir()
    for name in (
        "run_units.sh",
        "run_units.py",
        "unit_agent.py",
        "unit_checks.py",
        "unit_usage.py",
    ):
        shutil.copy2(ROOT / "scripts" / name, repo / "scripts" / name)
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(sys.executable)
    executable(
        repo / "scripts/check.sh",
        "#!/bin/sh\necho check.sh ran\n"
        'if [ "$TOOL_RESULT" = check ] && [ -f src/opencold/discovery_first.py ]; then exit 9; fi\n'
        'exit "${CHECK_EXIT:-0}"\n',
    )
    (repo / "scripts/move_defs.py").write_text("""
import json
import os
import sys
from pathlib import Path

mode = os.environ.get("TOOL_RESULT", "refuse")
unit_id = sys.argv[1]
if mode == "refuse" or (mode == "first-only" and unit_id != "01-first"):
    sys.exit(1)
source = Path("src/opencold/discovery.py")
source.write_text("\\n".join(source.read_text().splitlines()[:-1]) + "\\n")
features = Path("docs/plans/discovery-split/features.json")
unit = next(entry for entry in json.loads(features.read_text()) if entry["id"] == unit_id)
Path(unit["target_module"]).write_text("# moved definition\\n")
if mode == "dirty":
    Path("outside.txt").touch()
if mode == "golden":
    Path("tests/fixtures/discover_golden.json").write_text("changed\\n")
if mode == "partial":
    sys.exit(1)
print("AST equality: PASS (moved and remaining definitions)")
""")
    git(repo, "add", "--", ".gitignore", ".agents", "docs", "scripts", "src", "tests")
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
        if os.environ.get('CI_FAIL_SECOND') and '02-next' in git('log', '-1', '--format=%s'):
            sys.exit(1)
        sys.exit(int(os.environ.get('CI_EXIT', '0')))
    elif sys.argv[1:3] == ['run', 'view']:
        assert sys.argv[3] == '123'
        print(json.dumps({'headSha': git('rev-parse', 'HEAD'),
                          'conclusion': os.environ.get('CI_CONCLUSION', 'success')}))
    else:
        raise AssertionError(sys.argv)
    sys.exit()

home = Path.home()
assert home.name.startswith('opencold-agent-')
config = Path(os.environ['CODEX_HOME' if agent == 'codex' else 'CLAUDE_CONFIG_DIR'])
assert config.parent == home and not (home / '.agents').exists()
assert not (config / 'skills').exists()
auth = config / ('auth.json' if agent == 'codex' else '.credentials.json')
assert auth.read_text() == 'fixture credentials'
assert auth.stat().st_mode & 0o777 == 0o600
if any(arg.startswith('Runner preflight.') for arg in sys.argv):
    mode = os.environ.get('PREFLIGHT_RESULT', 'success')
    cwd = str(Path.cwd())
    pwd = '/wrong-directory' if mode == 'pwd' else cwd
    skills = [] if mode == 'no-review' else ['review']
    if mode == 'personal':
        skills.append('personal')
    if agent == 'codex':
        thread = '00000000-0000-0000-0000-000000000000'
        events = [
            {'type': 'thread.started', 'thread_id': thread},
            {'type': 'item.completed', 'item': {'type': 'command_execution',
                'command': '/bin/sh -lc pwd', 'exit_code': 0, 'aggregated_output': pwd}},
        ]
        catalog = '<skills_instructions>\\n## Skills\\n### Skill roots\\n'
        catalog += f'- `r0` = `{cwd}/.agents/skills`\\n### Available skills\\n'
        catalog += ''.join(
            f'- {skill}: Test skill (file: r0/{skill}/SKILL.md)\\n'
            for skill in skills
        )
        session = config / 'sessions' / f'rollout-test-{thread}.jsonl'
        session.parent.mkdir(exist_ok=True)
        session.write_text(json.dumps({'type': 'response_item', 'payload': {
            'role': 'developer', 'content': [{'text': catalog}],
        }}) + '\\n')
    else:
        events = [
            {'type': 'system', 'subtype': 'init', 'skills': skills},
            {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'pwd'}, 'id': 'pwd'}]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'pwd', 'content': pwd}]}},
        ]
    for event in events:
        print(json.dumps(event))
    sys.exit()

mode = os.environ.get('AGENT_RESULT', 'success')
if os.environ.get('EXPECT_RESTORED'):
    assert git('status', '--porcelain') == ''
    assert Path('src/opencold/discovery.py').read_text().count('\\n') == 405
    assert '"discovery.py": 405' in Path('tests/test_invariants.py').read_text()
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
notes = Path(os.environ['OPENCOLD_UNIT_NOTES'])
if mode == 'notes-symlink':
    notes.symlink_to(Path('scripts/check.sh').resolve())
else:
    notes.write_text('Fixture verification details.\\n')
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
    operator_home = tmp_path / "operator-home"
    operator_home.mkdir()
    monkeypatch.setenv("HOME", str(operator_home))
    for variable, name, auth in (
        ("CODEX_HOME", "codex-config", "auth.json"),
        ("CLAUDE_CONFIG_DIR", "claude-config", ".credentials.json"),
    ):
        config = operator_home / name
        (config / "skills").mkdir(parents=True)
        (config / auth).write_text("fixture credentials")
        monkeypatch.setenv(variable, str(config))
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


@pytest.mark.parametrize("batch_size", ["2", "3"])
def test_tool_units_batch_without_launching_agents(checkout, monkeypatch, batch_size):
    repo, calls, _ = checkout
    monkeypatch.setenv("TOOL_RESULT", "success")
    monkeypatch.setenv("PREFLIGHT_RESULT", "pwd")
    result = run(repo, "codex", "--push-every", batch_size, "--max-units", "3")
    assert result.returncode == 0, result.stderr
    assert [call[:3] for call in calls_from(calls)] == [
        ["gh", "run", "list"],
        ["gh", "run", "watch"],
        ["gh", "run", "view"],
    ]
    assert git(repo, "log", "-2", "--format=%s").splitlines() == [
        "Split discovery: 02-next (tool)",
        "Split discovery: 01-first (tool)",
    ]
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")
    assert git(repo, "status", "--porcelain") == ""
    assert '"discovery.py": 403' in (repo / "tests/test_invariants.py").read_text()
    progress = (repo / PLAN / "progress.md").read_text()
    assert "01-first" in progress and "405→404" in progress
    assert "02-next" in progress and "404→403" in progress
    assert progress.count("mode=tool") == 2
    with (repo / ".agent-logs/usage.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert [row["mode"] for row in rows] == ["tool", "tool"]
    assert all(row["input_tokens"] == row["output_tokens"] == "0" for row in rows)
    assert all(float(row["duration_seconds"]) >= 0 for row in rows)


@pytest.mark.parametrize("failure", ["partial", "dirty", "golden", "check"])
def test_tool_failure_restores_before_agent(checkout, monkeypatch, failure):
    repo, calls, _ = checkout
    monkeypatch.setenv("TOOL_RESULT", failure)
    monkeypatch.setenv("EXPECT_RESTORED", "1")
    result = run(repo, "codex", "--max-units", "1")
    assert result.returncode == 0, result.stderr
    assert git(repo, "log", "-1", "--format=%s") == "Split discovery: 01-first"
    assert [call[0] for call in calls_from(calls)].count("codex") == 2
    assert "mode=tool" not in (repo / PLAN / "progress.md").read_text()
    assert not (repo / "src/opencold/discovery_first.py").exists()


def test_failed_batch_prints_range(checkout, monkeypatch):
    repo, calls, _ = checkout
    baseline = git(repo, "rev-parse", "HEAD")
    monkeypatch.setenv("TOOL_RESULT", "success")
    monkeypatch.setenv("CI_EXIT", "1")
    result = run(repo, "codex", "--push-every", "2")
    assert result.returncode == 1, result.stderr
    head = git(repo, "rev-parse", "HEAD")
    assert f"{baseline}..{head}" in result.stderr
    assert git(repo, "rev-list", "--count", f"{baseline}..{head}") == "2"
    assert [call[0] for call in calls_from(calls)] == ["gh", "gh"]


def test_ci_range_starts_at_last_successful_push(checkout, monkeypatch):
    repo, _, _ = checkout
    monkeypatch.setenv("TOOL_RESULT", "success")
    monkeypatch.setenv("CI_FAIL_SECOND", "1")
    result = run(repo)
    assert result.returncode == 1, result.stderr
    head = git(repo, "rev-parse", "HEAD")
    green = git(repo, "rev-parse", "HEAD~1")
    assert f"{green}..{head}" in result.stderr


def test_mixed_batch_migrates_legacy_usage_rows(checkout, monkeypatch):
    repo, calls, _ = checkout
    logs = repo / ".agent-logs"
    logs.mkdir()
    usage_path = logs / "usage.csv"
    usage_path.write_text(
        "unit,agent,duration_seconds,input_tokens,output_tokens,cached_input_tokens,"
        "cache_creation_input_tokens\nold,codex,1.000,600000,2,500000,\n"
    )
    monkeypatch.setenv("TOOL_RESULT", "first-only")
    result = run(repo, "codex", "--push-every", "2")
    assert result.returncode == 0, result.stderr
    assert [call[0] for call in calls_from(calls)] == ["codex", "codex", "gh", "gh", "gh"]
    with usage_path.open() as stream:
        rows = list(csv.DictReader(stream))
    assert [row["mode"] for row in rows] == ["agent", "tool", "agent"]
    assert rows[0]["input_tokens"] == "600000" and rows[0]["cached_input_tokens"] == "500000"
    assert git(repo, "log", "-2", "--format=%s").splitlines() == [
        "Split discovery: 02-next",
        "Split discovery: 01-first (tool)",
    ]


def test_tool_ratchet_exception_removed_at_400_lines(checkout, monkeypatch):
    repo, _, _ = checkout
    source = repo / "src/opencold/discovery.py"
    source.write_text("\n".join(source.read_text().splitlines()[:401]) + "\n")
    ratchet = repo / "tests/test_invariants.py"
    ratchet.write_text(ratchet.read_text().replace("405", "401"))
    git(repo, "add", "--", "src/opencold/discovery.py", "tests/test_invariants.py")
    git(repo, "commit", "-m", "Set boundary")
    git(repo, "push", "origin", "main")
    monkeypatch.setenv("TOOL_RESULT", "success")
    result = run(repo)
    assert result.returncode == 0, result.stderr
    assert '"discovery.py"' not in ratchet.read_text()
    assert len(source.read_text().splitlines()) == 399


def test_real_mover_through_runner_in_temporary_repo(checkout, monkeypatch):
    import ruff

    repo, calls, _ = checkout
    shutil.copy2(ROOT / "scripts/move_defs.py", repo / "scripts/move_defs.py")
    # Keep retained code above the ratchet boundary while moving a small function.
    code = (
        "def retained():\n    return (\n"
        + "".join(f"        {number},\n" for number in range(405))
        + "    )\n\n\ndef moved():\n    return 1\n"
    )
    source = repo / "src/opencold/discovery.py"
    source.write_text(code)
    ratchet = repo / "tests/test_invariants.py"
    ratchet.write_text(ratchet.read_text().replace("405", str(len(code.splitlines()))))
    features = repo / PLAN / "features.json"
    units = json.loads(features.read_text())
    units[0]["functions"] = ["moved"]
    features.write_text(json.dumps(units))
    git(repo, "add", "--", "src", "tests", "scripts/move_defs.py", str(PLAN))
    git(repo, "commit", "-m", "Set real mover fixture")
    git(repo, "push", "origin", "main")
    monkeypatch.setenv("PYTHONPATH", str(Path(ruff.__file__).resolve().parent.parent))
    result = run(repo, "codex", "--max-units", "1")
    assert result.returncode == 0, result.stderr
    assert [call[0] for call in calls_from(calls)] == ["gh", "gh", "gh"]
    assert git(repo, "log", "-1", "--format=%s") == "Split discovery: 01-first (tool)"
    assert "def moved():" in (repo / "src/opencold/discovery_first.py").read_text()
    assert "def moved():" not in source.read_text()
    log = next((repo / ".agent-logs").glob("01-first-*"))
    assert "AST equality: PASS" in (log / "checks.log").read_text()


@pytest.mark.parametrize("agent", ["codex", "claude"])
@pytest.mark.parametrize(
    "mode,diagnostic", [("pwd", "pwd"), ("no-review", "review"), ("personal", "only advertised")]
)
def test_failed_agent_preflight_stops_before_first_unit(
    checkout, monkeypatch, agent, mode, diagnostic
):
    repo, calls, _ = checkout
    head = git(repo, "rev-parse", "HEAD")
    monkeypatch.setenv("PREFLIGHT_RESULT", mode)
    result = run(repo, agent)
    assert result.returncode == 1, result.stderr
    assert "preflight" in result.stderr and diagnostic in result.stderr
    assert len(calls_from(calls)) == 1
    log = next((repo / ".agent-logs").glob("01-first-*"))
    assert "move_defs.py" in (log / "checks.log").read_text()
    assert not (log / "stdout.jsonl").exists()
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "status", "--porcelain") == ""


def test_preflight_only_runs_without_starting_units(checkout):
    repo, calls, _ = checkout
    head = git(repo, "rev-parse", "HEAD")
    result = run(repo, "codex", "--preflight-only")
    assert result.returncode == 0, result.stderr
    assert "codex preflight passed" in result.stdout
    assert len(calls_from(calls)) == 1
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize("agent", ["codex", "claude"])
def test_success_runs_one_session_per_unit_and_logs_usage(checkout, agent):
    repo, calls, _ = checkout
    result = run(repo, agent)
    assert result.returncode == 0, result.stderr
    recorded = calls_from(calls)
    preflight, *sessions = [call for call in recorded if call[0] == agent]
    assert len(sessions) == 2
    assert any(arg.startswith("Runner preflight.") for arg in preflight)
    assert all(
        [arg for arg in call if arg != PROMPT]
        == [arg for arg in preflight if not arg.startswith("Runner preflight.")]
        for call in sessions
    )
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
            and "--ignore-user-config" in call
            for call in sessions
        )
    else:
        assert all(
            "-p" in call and "stream-json" in call and "dontAsk" in call for call in sessions
        )
        settings = json.loads(sessions[0][sessions[0].index("--settings") + 1])
        assert settings["disableBundledSkills"]
        assert settings["sandbox"]["failIfUnavailable"]
        assert not settings["sandbox"]["allowUnsandboxedCommands"]
        assert settings["sandbox"]["excludedCommands"] == []
        assert settings["sandbox"]["network"]["allowedDomains"] == []
        assert settings["sandbox"]["filesystem"]["denyWrite"] == [str(repo / ".git")]
    with (repo / ".agent-logs/usage.csv").open() as stream:
        usage = list(csv.DictReader(stream))
    assert [
        (row["unit"], row["agent"], row["input_tokens"], row["output_tokens"], row["mode"])
        for row in usage
    ] == [
        ("01-first", agent, "50", "25", "agent"),
        ("02-next", agent, "50", "25", "agent"),
    ]
    log = next((repo / ".agent-logs").glob("01-first-*"))
    stdout = log / "stdout.jsonl"
    assert json.loads(stdout.read_text())["usage"]["input_tokens"] == 50
    assert "diagnostic on stderr" in (log / "stderr.log").read_text()
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "log", "-2", "--format=%s").splitlines() == [
        "Split discovery: 02-next",
        "Split discovery: 01-first",
    ]
    assert git(repo, "log", "-1", "--format=%b") == "Fixture verification details."


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
@pytest.mark.parametrize("tool_result", ["refuse", "success"])
def test_precondition_failure_does_not_launch(
    checkout, tmp_path, monkeypatch, case, diagnostic, tool_result
):
    repo, calls, remote = checkout
    monkeypatch.setenv("TOOL_RESULT", tool_result)
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
    assert not list((repo / ".agent-logs").glob("01-first-*"))


@pytest.mark.parametrize(
    "mode,diagnostic",
    [
        ("exit", "agent exit 7"),
        ("agent-commit", "leave HEAD unchanged"),
        ("staged", "leave all changes unstaged"),
        ("no-pass", "passes count"),
        ("wrong-unit", "selected unit"),
        ("dirty", "unexpected changed paths"),
        ("notes-symlink", "commit body must be a regular file"),
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
    assert [call[0] for call in calls_from(calls)].count("codex") == 2
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
