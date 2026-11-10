"""Exercise agent protocol boundaries without starting model sessions."""

import json
import subprocess

import pytest

from evals import reviewer_eval
from scripts import reviewer_agent


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_reviewer_adapter_normalizes_usage_and_uses_read_only_cli(agent, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_CLI", agent)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "application-key")
    if agent == "claude":
        stdout = json.dumps(
            {
                "result": "VERDICT: PASS",
                "usage": {"input_tokens": 10, "output_tokens": 2},
                "total_cost_usd": 0.01,
            }
        )
    else:
        stdout = "\n".join(
            json.dumps(event)
            for event in [
                {"type": "item.completed", "item": {"type": "command_execution", "text": "noise"}},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "VERDICT: PASS"},
                },
                {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}},
            ]
        )

    def fake_run(cmd, **kwargs):
        assert cmd[0] == agent
        assert kwargs["cwd"] == tmp_path
        if agent == "claude":
            assert "ANTHROPIC_API_KEY" not in kwargs["env"]
            assert "--allowedTools" in cmd and "--disallowedTools" in cmd
        else:
            assert cmd[cmd.index("--sandbox") + 1] == "read-only"
            assert "hooks.Stop=[]" in cmd
            assert cmd[cmd.index("-a") + 1] == "never"
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(reviewer_agent.subprocess, "run", fake_run)
    result = reviewer_agent.run(reviewer_agent.selected_agent(), "review", tmp_path, 10)
    assert result["text"] == "VERDICT: PASS"
    assert not result["error"]
    assert result["usage"] == {
        "input_tokens": 10,
        "output_tokens": 2,
        "cost_usd": 0.01 if agent == "claude" else None,
    }


@pytest.mark.parametrize("output,returncode", [('{"result":"VERDICT: PASS"}', 1), ("bad JSON", 0)])
def test_failed_reviewer_never_scores_as_pass(output, returncode, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_CLI", "claude")
    monkeypatch.setattr(reviewer_eval, "ROOT", tmp_path)
    monkeypatch.setattr(reviewer_eval, "WORK", tmp_path / "work")
    case = tmp_path / "clean_example.patch"
    case.write_text("example diff")
    monkeypatch.setattr(
        reviewer_agent.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], returncode, output, "error"),
    )
    result = reviewer_eval.run_once(case, 1, tmp_path)
    assert result["verdict"] == "NONE"
    assert reviewer_eval.grade(case.name, result)["outcome"] == "false_alarm"
    assert not list((tmp_path / "work").iterdir())


def test_unknown_reviewer_cli_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_CLI", "unexpected")
    with pytest.raises(ValueError, match="AGENT_CLI"):
        reviewer_agent.selected_agent()


@pytest.mark.parametrize(
    "agent,output",
    [
        ("claude", '{"is_error":true,"result":"VERDICT: PASS"}'),
        ("codex", '{"type":"turn.failed"}'),
        (
            "codex",
            '{"type":"item.completed","item":{"type":"agent_message","text":"VERDICT: PASS"}}',
        ),
    ],
)
def test_incomplete_or_error_events_rejected(agent, output):
    with pytest.raises(ValueError):
        reviewer_agent.decode(agent, output)
