"""Test extraction against disposable source and queue files."""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/move_defs.py"
SOURCE = Path("src/opencold/discovery.py")
TARGET = SOURCE.with_name("discovery_fixture.py")


def fixture(root, text, functions, symbols=None):
    source = root / SOURCE
    source.parent.mkdir(parents=True)
    source.write_text(text, encoding="utf-8")
    plan = root / "docs/plans/discovery-split"
    plan.mkdir(parents=True)
    unit = {
        "id": "01-fixture",
        "target_module": str(TARGET),
        "functions": functions,
        "passes": False,
    }
    if symbols is not None:
        unit["description"] = f"Extract fixture. Symbols: {', '.join(symbols)}"
    (plan / "features.json").write_text(json.dumps([unit]), encoding="utf-8")
    return source, root / TARGET


def move(root):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "01-fixture"], cwd=root, capture_output=True, text=True
    )


def test_moves_decorated_function_and_immutable_constant(tmp_path):
    original = '''\
from __future__ import annotations

import os
from typing import final

# Used by the moved function.
SUFFIX = (".co.uk",)


# Keep the decorator and explanatory comment.
@final
def suffix(value: str) -> str:
    """Append the public suffix."""
    suffix = SUFFIX[0]  # inline detail
    return value + suffix
    # Keep trailing definition comments too.


def remain() -> str:
    return suffix(os.name)
'''
    source, target = fixture(tmp_path, original, ["suffix"], ["SUFFIX", "suffix"])
    result = move(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "AST equality: PASS" in result.stdout
    owner = target.read_text()
    assert "# Used by the moved function." in owner
    assert "# Keep the decorator and explanatory comment." in owner
    assert "# inline detail" in owner
    assert "# Keep trailing definition comments too." in owner
    assert "import os" not in owner
    assert "from typing import final" in owner
    assert "from opencold.discovery_fixture import" in source.read_text()
    assert "from typing import final" in source.read_text()
    before = [
        ast.dump(node)
        for node in ast.parse(original).body
        if isinstance(node, (ast.Assign, ast.FunctionDef))
    ][:2]
    after = [
        ast.dump(node)
        for node in ast.parse(owner).body
        if isinstance(node, (ast.Assign, ast.FunctionDef))
    ]
    assert before == after


@pytest.mark.parametrize(
    "text,functions,symbols,diagnostic",
    [
        ("CACHE = {}\n", [], ["CACHE"], "mutable"),
        ("def cached(values=[]):\n    return values\n", ["cached"], None, "mutable"),
        ("class Cache:\n    values = {}\n", ["Cache"], None, "mutable"),
        (
            "def moved():\n    return 2\n\nDEFAULT = moved()\nimport typing\n",
            ["moved"],
            None,
            "late top-level import",
        ),
        (
            "CACHE = None\n\ndef rebind():\n    global CACHE\n    CACHE = 1\n",
            ["rebind"],
            ["CACHE", "rebind"],
            "CACHE",
        ),
        ("LIMIT = 1\n\ndef pick():\n    return LIMIT\n", ["pick"], None, "LIMIT"),
        (
            "def pick():\n    from opencold import discovery\n    return discovery\n",
            ["pick"],
            None,
            "facade",
        ),
    ],
)
def test_refusal_leaves_both_files_untouched(tmp_path, text, functions, symbols, diagnostic):
    source, target = fixture(tmp_path, text, functions, symbols)
    result = move(tmp_path)
    assert result.returncode != 0
    assert diagnostic in result.stderr
    assert source.read_text() == text
    assert not target.exists()
