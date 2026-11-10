"""Eval the `review` skill (an inferential sensor) on labelled patch cases.

    python -m evals.reviewer_eval [--runs 2] [--workers 4] [--only NAME]

Each case in evals/reviewer/cases/ is a unified diff whose filename states the
expected result: `r<N>_*.patch` must be caught as rule N; `clean_*.patch` must PASS.
Every run is a fresh, headless Claude Code session (`claude -p`) with read-only tools,
given a NEUTRALLY named copy of the patch so the filename can't leak the answer.
Inferential sensors are non-deterministic, so each case runs `--runs` times and
disagreements between runs are reported.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "reviewer" / "cases"
WORK = ROOT / "evals" / "reviewer" / ".work"  # gitignored scratch for neutral copies
RESULTS = ROOT / "evals" / "results"
SKILL = ".agents/skills/review/SKILL.md"
TOOLS = "Read,Grep,Glob,Bash(git diff:*),Bash(git log:*),Bash(git show:*)"
DENY = "Edit,Write,NotebookEdit,WebFetch,WebSearch,Agent,Task"
TIMEOUT = 900

PROMPT = (
    "Read {skill} and follow it exactly to review the patch file at {patch}. "
    "This session is already a fresh context: do not spawn a subagent. "
    "Do not apply or modify anything. Print only the review output."
)


def expected(case: str) -> int | None:
    m = re.match(r"r(\d+)_", case)
    return int(m.group(1)) if m else None


def parse(text: str) -> dict:
    verdict = re.findall(r"VERDICT:\s*(PASS|FAIL)", text)
    return {
        "verdict": verdict[-1] if verdict else "NONE",
        "rules": sorted({int(n) for n in re.findall(r"\[R(\d+)\]", text)}),
    }


def _child_env() -> dict:
    """The reviewer session uses the user's Claude Code login. An ANTHROPIC_API_KEY in
    the environment (e.g. from the app's .env) would take precedence and may be invalid."""
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def run_once(case: Path, run: int, out_dir: Path) -> dict:
    tmp = WORK / uuid.uuid4().hex[:8]
    tmp.mkdir(parents=True)
    patch = tmp / "change.patch"
    shutil.copy(case, patch)
    cmd = [
        "claude",
        "-p",
        PROMPT.format(skill=SKILL, patch=patch.relative_to(ROOT)),
        "--allowedTools",
        TOOLS,
        "--disallowedTools",
        DENY,
        "--output-format",
        "text",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=_child_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        text = proc.stdout + ("\n[stderr]\n" + proc.stderr if proc.returncode else "")
    except subprocess.TimeoutExpired:
        text = "[timeout]"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    (out_dir / f"{case.stem}.run{run}.txt").write_text(text, encoding="utf-8")
    return {"case": case.name, "run": run, **parse(text)}


def grade(case: str, r: dict) -> dict:
    exp = expected(case)
    if exp is None:  # clean case
        ok = r["verdict"] == "PASS" and not r["rules"]
        return {"outcome": "correct_pass" if ok else "false_alarm", "false_positives": r["rules"]}
    caught = r["verdict"] == "FAIL" and exp in r["rules"]
    return {
        "outcome": "caught" if caught else "missed",
        "false_positives": [n for n in r["rules"] if n != exp],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", help="run a single case (filename)")
    args = ap.parse_args()

    cases = sorted(CASES.glob("*.patch"))
    if args.only:
        cases = [c for c in cases if c.name == args.only]
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out_dir = ROOT / "evals" / "reviewer" / "runs" / stamp
    out_dir.mkdir(parents=True)

    jobs = [(c, i) for c in cases for i in range(1, args.runs + 1)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        raw = list(pool.map(lambda j: run_once(j[0], j[1], out_dir), jobs))

    rows = [{**r, **grade(r["case"], r)} for r in raw]
    by_case: dict[str, list[dict]] = {}
    for r in rows:
        by_case.setdefault(r["case"], []).append(r)

    print(
        f"{'case':30} {'expect':7} "
        + " ".join(f"{'run' + str(i):24}" for i in range(1, args.runs + 1))
        + " agree"
    )
    for case, rs in sorted(by_case.items()):
        rs.sort(key=lambda r: r["run"])
        exp = expected(case)
        cells = [f"{r['outcome']}:{r['verdict']}{r['rules'] or ''}" for r in rs]
        agree = len({(r["verdict"], tuple(r["rules"])) for r in rs}) == 1
        print(
            f"{case:30} {('R' + str(exp)) if exp else 'PASS':7} "
            + " ".join(f"{c:24}" for c in cells)
            + f" {'yes' if agree else 'NO'}"
        )

    total = {
        k: sum(r["outcome"] == k for r in rows)
        for k in ("caught", "missed", "correct_pass", "false_alarm")
    }
    fps = sum(len(r["false_positives"]) for r in rows)
    disagreements = sorted(
        c for c, rs in by_case.items() if len({(r["verdict"], tuple(r["rules"])) for r in rs}) > 1
    )
    print(f"\nruns={len(rows)} {total} extra_rule_findings={fps} disagreements={disagreements}")

    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"reviewer-{stamp[:10]}-{sha}.json"
    path.write_text(
        json.dumps(
            {
                "runs_dir": str(out_dir.relative_to(ROOT)),
                "totals": total,
                "extra_rule_findings": fps,
                "disagreements": disagreements,
                "rows": rows,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"saved {path.relative_to(ROOT)} and raw outputs in {out_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
