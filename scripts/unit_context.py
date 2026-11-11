"""Build bounded unit briefs and retain a lossless progress archive."""

import ast
import json
import re
from pathlib import Path

PLAN = Path("docs/plans/discovery-split")
SOURCE = Path("src/opencold/discovery.py")


def progress_parts(text: str) -> tuple[str, list[str]]:
    # Historical tool entries were appended without headings. Treat each as a
    # session, alongside human/agent headings. Baseline and template stay put.
    starts = [
        match.start()
        for match in re.finditer(
            r"^## (?!Baseline|Session entry template).+|^- \d[\w-]+ mode=tool,.*", text, re.M
        )
    ]
    if not starts:
        return text, []
    return text[: starts[0]], [
        text[start:end] for start, end in zip(starts, [*starts[1:], len(text)], strict=True)
    ]


def compact_progress() -> list[str]:
    path = PLAN / "progress.md"
    prefix, entries = progress_parts(path.read_text(encoding="utf-8"))
    if len(entries) <= 5:
        return []
    archive = PLAN / "progress-archive.md"
    previous = (
        archive.read_text(encoding="utf-8")
        if archive.exists()
        else "# Discovery split progress archive\n\n"
    )
    archive.write_text(
        previous.rstrip() + "\n\n" + "".join(entries[:-5]).rstrip() + "\n", encoding="utf-8"
    )
    path.write_text(prefix + "".join(entries[-5:]).rstrip() + "\n", encoding="utf-8")
    return [str(path), str(archive)]


def section(text: str, title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if match is None:
        raise ValueError(f"Missing plan section: {title}")
    return match[0].rstrip()


def write_brief(unit: dict, reason: dict, log: Path) -> None:
    plan = (PLAN / "plan.md").read_text(encoding="utf-8")
    _, entries = progress_parts((PLAN / "progress.md").read_text(encoding="utf-8"))
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    definitions = {
        node.name: node.lineno
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    locations = []
    for name in unit.get("functions", []):
        if name not in definitions:
            raise ValueError(f"Cannot locate unit definition: {name}")
        locations.append(f"- {name}: {SOURCE}:{definitions[name]}")
    parts = [
        f"# Unit brief: {unit['id']}",
        "## Queue entry\n\n```json\n" + json.dumps(unit, indent=2) + "\n```",
        "## Tool refusal\n\n```json\n" + json.dumps(reason, indent=2) + "\n```",
        "## Definitions\n\n" + "\n".join(locations),
        section(plan, "Compatibility and seams"),
        section(plan, "Rules for coding sessions"),
        "## Last two progress entries\n\n" + "".join(entries[-2:]).rstrip(),
    ]
    (log / "brief.md").write_text("\n\n".join(parts) + "\n", encoding="utf-8")
