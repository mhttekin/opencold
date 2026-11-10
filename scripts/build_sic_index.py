"""Build src/opencold/sic_index_data.csv from the ONS UK SIC 2007 index workbook.

Source: ONS, "UK SIC 2007 Indexes with addendum December 2022 reformatted
September 2024" (Open Government Licence v3.0), from
https://www.ons.gov.uk/methodology/classificationsandstandards/ukstandardindustrialclassificationofeconomicactivities/uksic2007

Usage (build-time only; openpyxl is NOT a runtime dependency):
    .venv/bin/pip install openpyxl
    .venv/bin/python scripts/build_sic_index.py path/to/uksic2007indexes.xlsx

Reads the "Alphabetical Index" sheet (SIC 2007 code + activity text; the addendum
changes are already applied in it), keeps codes present in the vendored
Companies House SIC list, and writes a compact, sorted, deduplicated CSV.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "opencold" / "sic_index_data.csv"
SHEET = "Alphabetical Index"


def main(xlsx: str) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from opencold.sic_data import SIC_CODES

    known = {code for code, _ in SIC_CODES}
    ws = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)[SHEET]
    rows: set[tuple[str, str]] = set()
    skipped: set[str] = set()
    for code, _sic2003, activity, *_ in ws.iter_rows(min_row=4, values_only=True):
        if code is None or not activity:
            continue
        code = str(code).strip().zfill(5)
        text = " ".join(str(activity).split())
        if code in known:
            rows.add((code, text))
        else:
            skipped.add(code)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sic", "activity"])
        w.writerows(sorted(rows))
    print(f"wrote {len(rows)} rows ({len({c for c, _ in rows})} codes) to {OUT.relative_to(ROOT)}")
    print(f"skipped codes not in the Companies House SIC list: {sorted(skipped)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
