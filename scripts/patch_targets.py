"""Retarget test patches of discovery globals that a move would leave ineffective.

A test that patches ``opencold.discovery.<name>`` only reaches code that looks ``<name>``
up in discovery.py. Once a definition moves, it looks the name up in its new module.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

TESTS = Path("tests")
FACADE = "opencold.discovery"
SETTERS = {"setattr", "delattr"}


@dataclass(frozen=True)
class Edit:
    start: tuple[int, int]
    end: tuple[int, int]
    text: str


@dataclass(frozen=True)
class Patch:
    path: Path
    line: int
    name: str
    edits: tuple[Edit, ...]


def loaded_names(nodes: list[ast.stmt]) -> set[str]:
    return {
        node.id
        for root in nodes
        for node in ast.walk(root)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }


def module_globals(tree: ast.Module) -> set[str]:
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def facade_aliases(tree: ast.Module) -> set[str]:
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "opencold" and not node.level:
            aliases.update(a.asname or a.name for a in node.names if a.name == "discovery")
        elif isinstance(node, ast.Import):
            aliases.update(a.asname or a.name for a in node.names if a.name == FACADE)
    return aliases


def start(node: ast.AST) -> tuple[int, int]:
    return node.lineno, node.col_offset


def end(node: ast.AST) -> tuple[int, int]:
    return node.end_lineno, node.end_col_offset


def target_name(value: str) -> str | None:
    """``name`` for ``opencold.discovery.name``. A deeper path such as
    ``opencold.discovery.urllib.request.urlopen`` patches a shared object, not a binding."""
    prefix = FACADE + "."
    name = value[len(prefix) :] if value.startswith(prefix) else ""
    return name if name.isidentifier() else None


def find_patches(path: Path, text: str, owner: str) -> list[Patch]:
    """Patches of opencold.discovery.<name>, each with edits that retarget it to ``owner``."""
    tree = ast.parse(text)
    aliases = facade_aliases(tree)
    in_fstring = {
        id(part)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for part in ast.walk(node)
    }
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in in_fstring
            and (name := target_name(node.value))
        ):
            new = repr(f"opencold.{owner}.{name}")
            found.append(Patch(path, node.lineno, name, (Edit(start(node), end(node), new),)))
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        func, (module, attribute) = node.func, node.args[:2]
        is_object = isinstance(func, ast.Attribute) and ast.unparse(func).endswith("patch.object")
        is_setter = isinstance(func, ast.Attribute) and func.attr in SETTERS
        if (
            (is_object or is_setter)
            and ast.unparse(module) in aliases
            and isinstance(attribute, ast.Constant)
            and isinstance(attribute.value, str)
            and attribute.value.isidentifier()
        ):
            name = attribute.value
            edits = [Edit(start(module), end(attribute), repr(f"opencold.{owner}.{name}"))]
            if is_object:  # patch.object(module, "name", ...) -> patch("module.name", ...)
                edits.append(Edit(end(func.value), end(func), ""))
            found.append(Patch(path, node.lineno, name, tuple(edits)))
    return found


def apply(text: str, edits: list[Edit]) -> str:
    data = text.encode()
    offsets = [0]
    for line in data.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))

    def offset(position: tuple[int, int]) -> int:
        return offsets[position[0] - 1] + position[1]

    for edit in sorted(edits, key=lambda e: e.start, reverse=True):
        data = data[: offset(edit.start)] + edit.text.encode() + data[offset(edit.end) :]
    return data.decode()


def plan_retargets(
    tree: ast.Module, selected: list[ast.stmt], owner_tree: ast.Module, owner: str
) -> tuple[dict[Path, str], list[str], list[str]]:
    """Return rewritten test texts, retarget report lines and shared-target problems."""
    moved_refs = loaded_names(selected) & module_globals(owner_tree)
    staying = [
        node
        for node in tree.body
        if node not in selected and not isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    staying_refs = loaded_names(staying)
    rewritten, report, shared = {}, [], []
    for path in sorted(TESTS.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if FACADE not in text and "discovery" not in text:
            continue
        patches = [p for p in find_patches(path, text, owner) if p.name in moved_refs]
        for patch in patches:
            where = f"{path}:{patch.line} {FACADE}.{patch.name}"
            if patch.name in staying_refs:
                shared.append(f"{where} (also used by code that stays in discovery.py)")
            else:
                report.append(f"Retargeted patch: {where} -> opencold.{owner}.{patch.name}")
        if patches:
            rewritten[path] = apply(text, [e for p in patches for e in p.edits])
    return rewritten, report, shared
