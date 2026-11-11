"""Scoped fallback context and lossless progress retention."""

import json
from pathlib import Path

from scripts import unit_context as context


def test_compaction_retains_baseline_last_five_and_prerequisite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    context.PLAN.mkdir(parents=True)
    baseline = '# Log\n\n## Baseline — initial\n\n```json\n{"score": 1}\n```\n\n'
    entries = ["## golden-v2 — done\n\nproof\n\n"] + [
        f"- {i:02}-unit mode=tool, 10→9 lines\n\n" for i in range(7)
    ]
    progress = context.PLAN / "progress.md"
    progress.write_text(baseline + "".join(entries))
    context.compact_progress()
    assert progress.read_text() == baseline + "".join(entries[-5:]).rstrip() + "\n"
    archive = context.PLAN / "progress-archive.md"
    assert archive.read_text().endswith("".join(entries[:-5]).rstrip() + "\n")
    from scripts import unit_checks

    unit_checks.prerequisite({"requires": "golden-v2"})
    snapshot = progress.read_bytes(), archive.read_bytes()
    context.compact_progress()
    assert snapshot == (progress.read_bytes(), archive.read_bytes())
    progress.write_text(progress.read_text() + "\n- 08-unit mode=tool, 9→8 lines\n")
    context.compact_progress()
    assert archive.read_text().count("02-unit") == 1
    assert "08-unit" in progress.read_text()


def test_brief_uses_live_locations_rules_and_only_two_entries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    context.PLAN.mkdir(parents=True)
    (context.PLAN / "plan.md").write_text(
        "# Full plan\n\n## Target map\n\nUNRELATED TABLE\n\n"
        "## Compatibility and seams\n\nKeep identity.\n\n"
        "## Rules for coding sessions\n\n1. Keep assertions.\n\n"
        "## Running multiple sessions\n\nUNRELATED RUNNER DOCS\n"
    )
    (context.PLAN / "progress.md").write_text(
        "# Log\n\n## Baseline\n\nBASELINE\n\n## old\n\nOLD\n\n"
        "## recent\n\nRECENT\n\n- 02-unit mode=tool, 4→3 lines\n"
    )
    source = Path("src/opencold/discovery.py")
    source.parent.mkdir(parents=True)
    source.write_text("CONSTANT = 1\n\ndef moved():\n    return CONSTANT\n")
    log = Path(".agent-logs/unit-1")
    log.mkdir(parents=True)
    unit = {"id": "unit-1", "functions": ["moved"], "passes": False}
    reason = {"category": "mutable_state", "detail": "state audit needed"}
    context.write_brief(unit, reason, log)
    brief = (log / "brief.md").read_text()
    assert json.dumps(unit, indent=2) in brief
    assert "src/opencold/discovery.py:3" in brief
    assert "mutable_state" in brief and "state audit needed" in brief
    assert "Keep identity." in brief and "1. Keep assertions." in brief
    assert "RECENT" in brief and "02-unit" in brief
    assert "OLD" not in brief and "BASELINE" not in brief and "UNRELATED" not in brief
