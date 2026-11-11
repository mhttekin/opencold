"""Hide personal skill directories from the CLI process before it discovers skills."""

import json
import os
import shutil
import sys
from pathlib import Path


def skill_roots() -> list[Path]:
    home = Path.home()
    codex = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")
    repo = Path.cwd()
    allowed = (repo / ".agents/skills").resolve()
    roots = {
        home / ".agents/skills",
        home / ".claude/skills",
        home / ".claude/commands",
        codex / "skills",
        claude / "skills",
        claude / "commands",
        Path("/etc/codex/skills"),
        Path("/etc/claude-code/.claude/skills"),
        Path("/Library/Application Support/ClaudeCode/.claude/skills"),
        repo / ".codex/skills",
        repo / ".claude/commands",
    }
    claude_project = repo / ".claude/skills"
    if claude_project.resolve() != allowed:
        roots.add(claude_project)
    resolved = sorted({path.resolve() for path in roots})
    if any(allowed.is_relative_to(path) for path in resolved):
        raise ValueError("a personal skill directory overlaps the repository skill directory")
    return resolved


def isolate_skills(command: list[str]) -> list[str]:
    roots = skill_roots()
    if sys.platform == "darwin" and (sandbox := shutil.which("sandbox-exec")):
        denials = " ".join(
            f"(deny file-read* (subpath {json.dumps(str(path), ensure_ascii=False)}))"
            for path in roots
        )
        return [sandbox, "-p", f"(version 1) (allow default) {denials}", *command]
    if sys.platform.startswith("linux") and (sandbox := shutil.which("bwrap")):
        args = [sandbox, "--die-with-parent", "--bind", "/", "/", "--dev-bind", "/dev", "/dev"]
        for path in roots:
            if path.is_dir():
                args.extend(("--tmpfs", str(path)))
        return [*args, "--", *command]
    raise ValueError(
        "cannot isolate skill discovery: sandbox-exec (macOS) or bwrap (Linux) is required"
    )
