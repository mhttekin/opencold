#!/usr/bin/env python3
"""Move a discovery split unit whose definitions have static dependencies."""

from __future__ import annotations

import argparse
import ast
import copy
import json
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = Path("src/opencold/discovery.py")
FEATURES = Path("docs/plans/discovery-split/features.json")
DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
IMPORTS = (ast.Import, ast.ImportFrom)


class Refusal(ValueError):
    """The requested move needs manual review."""

    def __init__(self, detail: str, category: str = "unsupported_structure"):
        super().__init__(detail)
        self.category = category


def parse(source: str) -> ast.Module:
    return ast.parse(source, type_comments=True)


def load_unit(unit_id: str) -> tuple[Path, set[str]]:
    units = json.loads(FEATURES.read_text(encoding="utf-8"))
    matches = [unit for unit in units if unit["id"] == unit_id]
    if len(matches) != 1 or matches[0]["passes"] is not False:
        raise Refusal(f"expected one pending unit named {unit_id!r}")
    unit = matches[0]
    target = Path(unit["target_module"])
    if target.parent != SOURCE.parent or not re.fullmatch(r"discovery_[a-z0-9_]+\.py", target.name):
        raise Refusal(f"invalid target module {target}")
    if target.exists() or target.is_symlink():
        raise Refusal(f"target already exists: {target}")
    functions = set(unit["functions"])
    _, marker, listed = unit.get("description", "").partition("Symbols:")
    symbols = {name.strip() for name in listed.split(",")} if marker else functions
    if not symbols or not functions <= symbols or not all(name.isidentifier() for name in symbols):
        raise Refusal("unit has missing or inconsistent definitions")
    return target, symbols


def binding(node: ast.stmt) -> str | None:
    if isinstance(node, DEFINITIONS):
        return node.name
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ):
        return node.targets[0].id
    return None


def immutable(value: ast.expr | None) -> bool:
    if isinstance(value, ast.Constant):
        return True
    if isinstance(value, ast.Tuple):
        return all(immutable(element) for element in value.elts)
    return (
        isinstance(value, ast.Call)
        and ast.unparse(value.func) == "re.compile"
        and not value.keywords
        and all(
            isinstance(arg, ast.Constant)
            or (isinstance(arg, ast.Attribute) and ast.unparse(arg.value) == "re")
            for arg in value.args
        )
    )


def has_mutable_literal(value: ast.expr) -> bool:
    containers = (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)
    return any(isinstance(part, containers) for part in ast.walk(value))


class ModuleWrites(ast.NodeVisitor):
    def __init__(self):
        self.names: set[str] = set()

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_FunctionDef(self, node):
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_ClassDef = visit_FunctionDef


def select(tree: ast.Module, names: set[str]) -> list[ast.stmt]:
    selected = [node for node in tree.body if binding(node) in names]
    found = {binding(node) for node in selected}
    if found != names or len(selected) != len(names):
        raise Refusal(
            f"missing or multiply bound top-level definitions: {sorted(names - found) or sorted(names)}"
        )
    writes = ModuleWrites()
    for node in tree.body:
        if node not in selected:
            writes.visit(node)
    globals_in_unit = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            writes.names.update(node.names)
    unsafe = names & writes.names
    for node in selected:
        name = binding(node)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and not immutable(node.value):
            unsafe.add(name)
        if isinstance(node, DEFINITIONS):
            for decorator in node.decorator_list:
                callee = decorator.func if isinstance(decorator, ast.Call) else decorator
                if ast.unparse(callee).split(".")[-1] in {"cache", "lru_cache"}:
                    unsafe.add(name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = [
                *node.args.defaults,
                *(value for value in node.args.kw_defaults if value is not None),
            ]
            if any(has_mutable_literal(value) for value in defaults):
                unsafe.add(name)
        if isinstance(node, ast.ClassDef) and any(
            isinstance(member, (ast.Assign, ast.AnnAssign))
            and member.value is not None
            and has_mutable_literal(member.value)
            for member in node.body
        ):
            unsafe.add(name)
        for child in ast.walk(node):
            if isinstance(child, ast.Global):
                globals_in_unit.update(child.names)
            if isinstance(child, ast.Import) and any(
                alias.name == "opencold.discovery" for alias in child.names
            ):
                raise Refusal(f"{name} imports the discovery facade", "facade_dependency")
            if isinstance(child, ast.ImportFrom) and (
                child.module in {"opencold.discovery", "discovery"}
                or (
                    (child.module == "opencold" or child.level)
                    and any(alias.name == "discovery" for alias in child.names)
                )
            ):
                raise Refusal(f"{name} imports the discovery facade", "facade_dependency")
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id in {"globals", "eval", "exec"}
            ):
                raise Refusal(f"{name} uses dynamic name lookup", "dynamic_lookup")
    if unsafe or globals_in_unit:
        raise Refusal(
            f"mutable or rebound module-level state: {', '.join(sorted(unsafe | globals_in_unit))}",
            "mutable_state",
        )
    return selected


def span(lines: list[str], node: ast.stmt) -> tuple[int, int]:
    decorators = getattr(node, "decorator_list", [])
    first = min([node.lineno, *(item.lineno for item in decorators)]) - 1
    start = first
    for index in range(first - 1, -1, -1):
        if lines[index].startswith("#"):
            start = index
        elif lines[index].strip():
            break
    end = node.end_lineno
    for index in range(end, len(lines)):
        line = lines[index]
        if line[:1].isspace() and line.lstrip().startswith("#"):
            end = index + 1
        elif line.strip():
            break
    return start, end


def ruff(text: str, path: Path, *args: str, findings: bool = False) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", *args, "--stdin-filename", str(path), "-"],
        input=text,
        text=True,
        capture_output=True,
    )
    if result.returncode not in ((0, 1) if findings else (0,)):
        raise Refusal(
            f"Ruff could not prepare {path}: {result.stdout.strip() if not result.stderr else result.stderr.strip()}",
            "unresolved_dependency"
            if "--select" in args and "F821,F822,F823" in args
            else "validation_failed",
        )
    return result.stdout


def owner_imports(tree: ast.Module) -> str:
    imports = copy.deepcopy([node for node in tree.body if isinstance(node, IMPORTS)])
    for node in imports:
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
            raise Refusal("wildcard imports prevent dependency checking")
        for alias in node.names:
            if alias.name == alias.asname:
                alias.asname = None
    return "\n".join(ast.unparse(node) for node in imports)


def preserve_facade_imports(text: str) -> str:
    findings = json.loads(
        ruff(text, SOURCE, "check", "--select", "F401", "--output-format", "json", findings=True)
    )
    lines = text.splitlines()
    for row in {finding["noqa_row"] for finding in findings}:
        line = lines[row - 1]
        lines[row - 1] = line + (", F401" if "# noqa:" in line else "  # noqa: F401")
    return "\n".join(lines) + "\n"


def prepare(original: str, target: Path, names: set[str]) -> tuple[str, str]:
    tree = parse(original)
    selected = select(tree, names)
    anchor = max((node.end_lineno for node in tree.body if isinstance(node, IMPORTS)), default=0)
    if any(node.lineno <= anchor for node in selected):
        raise Refusal("a late top-level import would delay the facade re-exports")
    if not anchor and ast.get_docstring(tree) is not None:
        anchor = tree.body[0].end_lineno
    lines = original.splitlines(keepends=True)
    spans = [span(lines, node) for node in selected]
    for (start, end), node in zip(spans, selected, strict=True):
        # An adjacent statement on the same physical line cannot be moved alone.
        if any(
            other is not node and start < other.end_lineno and other.lineno <= end
            for other in tree.body
        ):
            raise Refusal(f"overlapping source statements around {binding(node)}")
    pieces = ["".join(lines[start:end]).rstrip() for start, end in spans]
    owner = "\n\n".join([owner_imports(tree), *pieces]).lstrip() + "\n"
    owner = ruff(owner, target, "check", "--fix", "--select", "F401,I")
    ruff(owner, target, "check", "--select", "F821,F822,F823")
    owner = ruff(owner, target, "format")

    reexport = f"from opencold.{target.stem} import {', '.join(sorted(names))}\n"
    if any(start < anchor < end for start, end in spans):
        raise Refusal("facade import insertion overlaps moved source")
    removed = {index for start, end in spans for index in range(start, end)}
    facade_lines = [reexport] if anchor == 0 else []
    for index, line in enumerate(lines):
        if index not in removed:
            facade_lines.append(line)
        if index + 1 == anchor:
            facade_lines.append(reexport)
    facade = ruff("".join(facade_lines), SOURCE, "check", "--fix", "--select", "I")
    facade = preserve_facade_imports(ruff(facade, SOURCE, "format"))
    ruff(facade, SOURCE, "check", "--select", "F401,F821,F822,F823,I")
    ruff(facade, SOURCE, "format", "--check")
    original_defs = [ast.dump(node) for node in selected]
    new_defs = [ast.dump(node) for node in parse(owner).body if not isinstance(node, IMPORTS)]
    retained = [
        ast.dump(node)
        for node in tree.body
        if node not in selected and not isinstance(node, IMPORTS)
    ]
    if new_defs != original_defs or retained != [
        ast.dump(node) for node in parse(facade).body if not isinstance(node, IMPORTS)
    ]:
        raise Refusal("AST equality check failed")
    if len(owner.splitlines()) > 400:
        raise Refusal("target exceeds the 400-line limit")
    if len(facade.splitlines()) >= len(original.splitlines()):
        raise Refusal("facade did not shrink")
    compile(owner, str(target), "exec")
    compile(facade, str(SOURCE), "exec")
    return facade, owner


def save(facade: str, target: Path, owner: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=SOURCE.parent, delete=False
    ) as stream:
        pending = Path(stream.name)
        try:
            stream.write(facade)
            stream.close()
            pending.chmod(stat.S_IMODE(SOURCE.stat().st_mode))
            with target.open("x", encoding="utf-8") as output:
                try:
                    output.write(owner)
                    output.close()
                    pending.replace(SOURCE)
                except OSError:
                    target.unlink()
                    raise
        finally:
            pending.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unit_id")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing files")
    args = parser.parse_args()
    try:
        target, names = load_unit(args.unit_id)
        original = SOURCE.read_text(encoding="utf-8")
        facade, owner = prepare(original, target, names)
        if not args.dry_run:
            save(facade, target, owner)
    except (OSError, SyntaxError, ValueError, KeyError, TypeError) as exc:
        print(
            json.dumps({"category": getattr(exc, "category", "invalid_input"), "detail": str(exc)}),
            file=sys.stderr,
        )
        return 1
    action = "Would move" if args.dry_run else "Moved"
    print(f"{action} {len(names)} definitions to {target}: {', '.join(sorted(names))}")
    print(f"discovery.py: {len(original.splitlines())} -> {len(facade.splitlines())} lines")
    print("AST equality: PASS (moved and remaining definitions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
