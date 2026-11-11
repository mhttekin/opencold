"""Record runner usage and preserve older agent rows when adding the mode column."""

import csv
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

TOKENS = ("input_tokens", "output_tokens", "cached_input_tokens", "cache_creation_input_tokens")
OLD_HEADER = ("unit", "agent", "duration_seconds", *TOKENS)
HEADER = (*OLD_HEADER, "mode")


def write_usage(path: Path, row: tuple) -> None:
    if path.exists() and path.stat().st_size:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.reader(stream)
            header = tuple(next(reader))
            if header == OLD_HEADER:
                with NamedTemporaryFile(
                    mode="w", newline="", encoding="utf-8", dir=path.parent, delete=False
                ) as pending:
                    temp = Path(pending.name)
                    try:
                        writer = csv.writer(pending)
                        writer.writerow(HEADER)
                        writer.writerows([*old, "agent"] for old in reader)
                        pending.close()
                        temp.replace(path)
                    finally:
                        temp.unlink(missing_ok=True)
            elif header != HEADER:
                raise ValueError(f"unexpected usage CSV header in {path}")
    with path.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        if stream.tell() == 0:
            writer.writerow(HEADER)
        writer.writerow(row)


def record_tool_usage(path: Path, unit: str, duration: float) -> None:
    write_usage(path, (unit, "", f"{duration:.3f}", *(0 for _ in TOKENS), "tool"))


def record_agent_usage(path: Path, agent: str, unit: str, duration: float, stdout: Path) -> None:
    totals = {}
    event_type = "turn.completed" if agent == "codex" else "result"
    with stdout.open(encoding="utf-8", errors="replace") as stream:
        for record in stream:
            try:
                event = json.loads(record)
            except ValueError:
                continue  # An interrupted session can leave a partial record.
            if not isinstance(event, dict) or event.get("type") != event_type:
                continue
            usage = event.get("usage")
            if isinstance(usage, dict):
                if agent == "claude":
                    usage["cached_input_tokens"] = usage.get("cache_read_input_tokens")
                for key in TOKENS:
                    value = usage.get(key)
                    if type(value) is int and value >= 0:
                        totals[key] = totals.get(key, 0) + value
    if totals:
        write_usage(
            path,
            (unit, agent, f"{duration:.3f}", *(totals.get(key, "") for key in TOKENS), "agent"),
        )
