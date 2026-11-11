"""Regression: the test suite must not depend on (or read) the repo's local .env."""

import fnmatch
import os
import runpy
from pathlib import Path

import pytest

from opencold import config

ROOT = Path(__file__).resolve().parents[1]
PROBE = "OPENCOLD_DOTENV_PROBE"


@pytest.fixture
def cwd_with_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(f"{PROBE}=from-file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "_DOTENV_LOADED", False)
    monkeypatch.delenv(PROBE, raising=False)
    yield tmp_path
    os.environ.pop(PROBE, None)


def test_suite_disables_implicit_dotenv(cwd_with_dotenv):
    assert os.environ.get("OPENCOLD_NO_DOTENV")
    config.load_dotenv()
    assert PROBE not in os.environ


def test_implicit_dotenv_still_loads_outside_tests(cwd_with_dotenv, monkeypatch):
    monkeypatch.delenv("OPENCOLD_NO_DOTENV")
    config.load_dotenv()
    assert os.environ[PROBE] == "from-file"


def test_unreadable_dotenv_is_silent(cwd_with_dotenv, monkeypatch):
    def denied(self, *args, **kwargs):
        raise PermissionError(1, "Operation not permitted", str(self))

    monkeypatch.delenv("OPENCOLD_NO_DOTENV")
    monkeypatch.setattr(Path, "is_file", denied)
    config.load_dotenv()  # sandboxes deny even stat on .env
    assert PROBE not in os.environ


def test_collection_skips_dotenv_files():
    globs = runpy.run_path(str(ROOT / "conftest.py"))["collect_ignore_glob"]
    for name in (".env", ".env.local"):
        assert any(fnmatch.fnmatch(name, g) for g in globs)
