"""Turn a `discover` output CSV into an unlabelled sheet for Mehmet to label.

    python -m evals.to_label <discover_output.csv> <evals/to_label/out.csv>

Columns: website, company_name_as_output, match_confidence, summary, expected.
`expected` is ALWAYS left empty: labels are ground truth owned by Mehmet, so this
script never guesses them. The blank gap row and REVIEW BELOW banner are skipped.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

COLUMNS = ["website", "company_name_as_output", "match_confidence", "summary", "expected"]
SUMMARY_CHARS = 300


def build(src: Path, dst: Path) -> int:
    with open(src, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("website") or "").strip()]
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "website": r["website"],
                    "company_name_as_output": r.get("company", ""),
                    "match_confidence": r.get("match_confidence", ""),
                    "summary": " ".join((r.get("company_summary") or "").split())[:SUMMARY_CHARS],
                    "expected": "",
                }
            )
    return len(rows)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(build(Path(sys.argv[1]), Path(sys.argv[2])), "rows")
