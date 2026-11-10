"""Run every eval, print a summary table, and save results JSON.

    python -m evals.run_all [--record] [--discover-csv PATH] [--baseline]

Writes evals/results/<YYYY-MM-DD>-<git short sha>.json. With --baseline (or when
evals/results/baseline.json is missing) the run is also saved as baseline.json.
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
from pathlib import Path

from evals import discover_eval, sic_eval

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
DEFAULT_DISCOVER_CSV = ROOT / "artifacts" / "discover_tr_pallets_2026-11-10.csv"


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except Exception:
        return "nogit"


def _fmt(x) -> str:
    return "n/a" if x is None else (f"{x:.2f}" if isinstance(x, float) else str(x))


def _delta(now, base) -> str:
    if not isinstance(now, (int, float)) or not isinstance(base, (int, float)) or now == base:
        return ""
    return f" ({now - base:+.2f})" if isinstance(now, float) else f" ({now - base:+d})"


def print_summary(result: dict, baseline: dict | None) -> None:
    print("\n=== Eval summary ===")
    for section in ("sic", "discover"):
        print(f"\n{section}")
        base = (baseline or {}).get(section, {}).get("metrics", {})
        for k, v in result[section]["metrics"].items():
            print(f"  {k:20} {_fmt(v):>6}{_delta(v, base.get(k))}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--record", action="store_true", help="re-record network cassettes")
    ap.add_argument("--discover-csv", type=Path, default=DEFAULT_DISCOVER_CSV)
    ap.add_argument("--baseline", action="store_true", help="also save as baseline.json")
    args = ap.parse_args()

    sic = sic_eval.run(record=args.record)
    sic_eval.print_report(sic)
    print()
    disc = discover_eval.score(args.discover_csv)
    discover_eval.print_report(disc)

    sha = _git_sha()
    today = datetime.date.today().isoformat()
    result = {"date": today, "git_sha": sha, "sic": sic, "discover": disc}

    baseline_path = RESULTS / "baseline.json"
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else None
    print_summary(result, baseline)

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{today}-{sha}.json"
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    out.write_text(payload, encoding="utf-8")
    print(f"\nSaved {out.relative_to(ROOT.parent)}")
    if args.baseline or baseline is None:
        baseline_path.write_text(payload, encoding="utf-8")
        print(f"Saved {baseline_path.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()
