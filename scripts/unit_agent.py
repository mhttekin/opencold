"""Set up scoped CLI homes and check evidence from the agent preflight."""

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

PREFLIGHT_PROMPT = (
    "Runner preflight. Call the shell tool with exactly pwd as the command and its normal "
    "sandbox settings. After the tool returns, stop. Do not modify files or run other commands."
)


@contextmanager
def agent_environment(agent: str):
    env = os.environ.copy()
    home = Path.home()
    with TemporaryDirectory(prefix="opencold-agent-") as directory:
        scoped_home = Path(directory)
        env["HOME"] = directory
        if agent == "codex":
            key, default, auth = "CODEX_HOME", ".codex", "auth.json"
        else:
            key, default, auth = "CLAUDE_CONFIG_DIR", ".claude", ".credentials.json"
        source = Path(env.get(key) or home / default) / auth
        config = scoped_home / default
        config.mkdir(mode=0o700)
        env[key] = str(config)
        # The CLI can update its own copy if it refreshes a file-based login.
        if source.is_file():
            shutil.copyfile(source, config / auth)
            (config / auth).chmod(0o600)
        yield env


def agent_command(agent: str, prompt: str, git_dirs: list[str]) -> list[str]:
    if agent == "codex":
        return [
            "codex",
            "-a",
            "never",
            "exec",
            "--ignore-rules",
            "--ignore-user-config",
            "--disable",
            "plugins",
            "--disable",
            "apps",
            "-c",
            "skills.bundled.enabled=false",
            "--sandbox",
            "workspace-write",
            "-c",
            "sandbox_workspace_write.network_access=false",
            "-c",
            "sandbox_workspace_write.writable_roots=[]",
            "--json",
            prompt,
        ]
    settings = {
        "disableBundledSkills": True,
        "permissions": {
            "allow": ["Edit(./**)", "Write(./**)"],
            "deny": ["Edit(./.git)", "Edit(./.git/**)"],
        },
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "excludedCommands": [],
            "network": {"allowedDomains": []},
            "filesystem": {"denyWrite": sorted({str(Path.cwd() / ".git"), *git_dirs})},
        },
    }
    return [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
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


def wait_for_agent(
    command: list[str],
    stdout: Path,
    stderr: Path,
    timeout: float,
    *,
    env: dict[str, str] | None = None,
) -> int:
    with stdout.open("wb") as out, stderr.open("wb") as err:
        with subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=True,
            env=env,
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


def json_events(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def codex_review_only(events: list[dict], config: Path) -> bool:
    thread = next((e["thread_id"] for e in events if e["type"] == "thread.started"), "")
    if not re.fullmatch(r"[0-9a-f-]{36}", thread):
        return False
    rollout = next((config / "sessions").rglob(f"rollout-*-{thread}.jsonl"), None)
    if rollout is None:
        return False
    for event in json_events(rollout):
        item = event["payload"]
        if event["type"] != "response_item" or item.get("role") != "developer":
            continue
        for block in item.get("content", []):
            content = block.get("text", "")
            if "### Available skills\n" not in content:
                continue
            roots, catalog = content.split("### Available skills\n", 1)
            if not re.search(r"^#{1,2} Skills$", roots, re.MULTILINE):
                continue
            entries = re.findall(r"^- ([^:\n]+): (.+)$", catalog, re.MULTILINE)
            if len(entries) != 1 or entries[0][0] != "review":
                return False
            location = re.search(r"\(file: (.+)\)$", entries[0][1])
            if location is None:
                return False
            path = Path(location[1])
            if not path.is_absolute():
                aliases = dict(re.findall(r"^- `(r\d+)` = `([^`]+)`$", roots, re.MULTILINE))
                if not path.parts or path.parts[0] not in aliases:
                    return False
                path = Path(aliases[path.parts[0]]).joinpath(*path.parts[1:])
            return path == Path.cwd() / ".agents/skills/review/SKILL.md"
    return False


def claude_pwd(events: list[dict], cwd: str) -> bool:
    calls = set()
    for event in events:
        for block in event.get("message", {}).get("content", []):
            if (
                block.get("type") == "tool_use"
                and block.get("name") == "Bash"
                and block.get("input", {}).get("command") == "pwd"
            ):
                calls.add(block["id"])
            if (
                block.get("type") == "tool_result"
                and block.get("tool_use_id") in calls
                and not block.get("is_error")
                and str(block.get("content", "")).strip() == cwd
            ):
                return True
    return False


def verify_preflight(agent: str, stdout: Path, env: dict[str, str]) -> None:
    events = list(json_events(stdout))
    cwd = str(Path.cwd().resolve())
    if agent == "codex":
        items = [event["item"] for event in events if event["type"] == "item.completed"]
        pwd_ok = False
        for item in items:
            if item["type"] != "command_execution" or item.get("exit_code") != 0:
                continue
            command = shlex.split(item["command"])
            if command == ["pwd"] or command[1:] in (["-lc", "pwd"], ["-c", "pwd"]):
                pwd_ok |= item.get("aggregated_output", "").strip() == cwd
        review_only = codex_review_only(events, Path(env["CODEX_HOME"]))
    else:
        pwd_ok = claude_pwd(events, cwd)
        init = next((e for e in events if e["type"] == "system" and e["subtype"] == "init"), {})
        review_only = init.get("skills") == ["review"]
    if not pwd_ok:
        raise ValueError("no successful pwd tool result for the repository")
    if not review_only:
        raise ValueError("expected the repository review skill as the only advertised skill")
