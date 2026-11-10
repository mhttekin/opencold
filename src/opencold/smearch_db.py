"""SQLite store of companies smearch has already surfaced, so repeat runs return
*fresh* companies instead of the same top-ranked ones every time.

This is smearch's default behaviour: each run records the company numbers it
outputs (the enriched top-N); the next run skips any already-recorded company
and -- when a whole page is already seen -- walks on to the next page. The
`--no-db` flag turns this off for a stateless test run (no reads, no writes).

The store is intentionally tiny: one table keyed by `company_number`, plus a
little context (name, the company's SICs, the ICP, a timestamp) for future
features that want to reuse the seen-set / index. Dedup is global by company
number -- a company surfaced under any search won't resurface under another.

Path: COMPANIES_HOUSE-style override via OPENCOLD_SMEARCH_DB, else
~/.opencold/smearch.db (alongside config.json).
"""
from __future__ import annotations

import datetime
import os
import sqlite3
from pathlib import Path

from opencold import config

_ENV_PATH = "OPENCOLD_SMEARCH_DB"
_DB_NAME = "smearch.db"
_PARAM_CHUNK = 500  # stay well under SQLite's variables-per-query limit


def default_db_path() -> Path:
    """~/.opencold/smearch.db, or the OPENCOLD_SMEARCH_DB override (tests, alt
    stores). ':memory:' is honoured by connect() for an ephemeral DB."""
    override = os.environ.get(_ENV_PATH)
    return Path(override) if override else (config.CONFIG_DIR / _DB_NAME)


def connect(path: str | os.PathLike | None = None) -> sqlite3.Connection:
    """Open (creating if needed) the seen-companies DB and ensure its schema."""
    p = str(path) if path is not None else str(default_db_path())
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS enriched_companies (
               company_number TEXT PRIMARY KEY,
               company_name   TEXT,
               sic_codes      TEXT,
               icp            TEXT,
               created_at     TEXT
           )"""
    )
    conn.commit()
    return conn


def seen_numbers(conn: sqlite3.Connection, numbers) -> set[str]:
    """The subset of `numbers` already recorded, via batched `IN (...)` queries."""
    nums = [n for n in numbers if n]
    out: set[str] = set()
    for i in range(0, len(nums), _PARAM_CHUNK):
        chunk = nums[i:i + _PARAM_CHUNK]
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT company_number FROM enriched_companies "
            f"WHERE company_number IN ({placeholders})",
            chunk,
        )
        out.update(r[0] for r in rows)
    return out


def mark_enriched(conn: sqlite3.Connection, rows, *, icp: str = "") -> int:
    """Record each row's company_number as surfaced. INSERT OR IGNORE keeps the
    first-seen row, so re-recording is a no-op. Returns the count newly inserted.

    Rows without a company_number are skipped (nothing to dedup on)."""
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    payload = [
        (r.get("company_number", ""), r.get("company_name", ""),
         r.get("sic_codes", ""), icp, stamp)
        for r in rows if r.get("company_number")
    ]
    if not payload:
        return 0
    before = conn.total_changes
    conn.executemany(
        """INSERT OR IGNORE INTO enriched_companies
               (company_number, company_name, sic_codes, icp, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        payload,
    )
    conn.commit()
    return conn.total_changes - before
