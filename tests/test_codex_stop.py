"""Stop decisions use crafted host inputs without running the shared checks."""

import json
import subprocess
import sys
from io import StringIO

import pytest

from scripts import codex_stop

REASON = (
    "Checks failed. Fix the failures and rerun ./scripts/check.sh. "
    "Log: /repo/.agent-logs/check.example\n"
    "FAILED tests/test_example.py::test_example\n"
)


@pytest.mark.parametrize("active", [False, True])
def test_passing_checks_allow_stop(active):
    assert codex_stop.stop_response(json.dumps({"stop_hook_active": active}), 0, "") == {}


@pytest.mark.parametrize("payload", ['{"stop_hook_active": false}', "{}"])
def test_first_failure_requests_continuation(payload):
    assert codex_stop.stop_response(payload, 2, REASON) == {
        "decision": "block",
        "reason": REASON,
    }


def test_repeated_failure_warns_without_requesting_continuation():
    response = codex_stop.stop_response('{"stop_hook_active": true}', 2, REASON)
    assert response == {"systemMessage": "checks still failing, see .agent-logs/check.example"}
    assert "decision" not in response


def test_repeated_failure_without_log_still_warns():
    response = codex_stop.stop_response('{"stop_hook_active": true}', 1, "gate unavailable")
    assert response == {"systemMessage": "checks still failing: gate unavailable"}


def test_main_reads_stdin_and_emits_nonblocking_json(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", StringIO('{"stop_hook_active": true}'))

    def fake_run(command, **kwargs):
        assert command == ["./scripts/agent-check.sh"]
        assert kwargs == {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True}
        return subprocess.CompletedProcess(command, 2, REASON)

    monkeypatch.setattr(codex_stop.subprocess, "run", fake_run)
    codex_stop.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "systemMessage": "checks still failing, see .agent-logs/check.example"
    }
    assert captured.err == ""
