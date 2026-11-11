from __future__ import annotations

import csv

from opencold.discovery_csv import COMPANY_CSV_FIELDS, COMPANY_PEOPLE_FIELDS, WALL_BANNER


def write_company_csv(rows: list[dict], output: str) -> None:
    """Write company leads; draws a visual wall between verified and the rest.

    Verified rows are written first, then a blank gap row and a banner divider,
    then the review/rejected rows — so opened in a spreadsheet the genuinely
    verified Top-N sit clearly above the pile that needs review.
    """
    fieldnames = list(COMPANY_CSV_FIELDS)
    if rows and any("contact_name" in r for r in rows):
        fieldnames += COMPANY_PEOPLE_FIELDS
    has_verified = any(r.get("match_confidence") == "verified" for r in rows)
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        wall_drawn = False
        for row in rows:
            if (
                not wall_drawn
                and has_verified
                and row.get("match_confidence") not in ("verified", "", None)
            ):
                writer.writerow({})  # blank gap row
                writer.writerow({"company": WALL_BANNER})
                wall_drawn = True
            writer.writerow(row)
