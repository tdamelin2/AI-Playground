"""CSV export: every database table plus the weekly measures, for analysis in R."""

from __future__ import annotations

import csv
from pathlib import Path

from ai_island.measure.weekly import DEFAULT_WEEK_TICKS, weekly_measures
from ai_island.storage.db import TABLES, RunDB

WEEKLY_FILE = "weekly_measures.csv"
WEEKLY_COLUMNS = ("week", "measure", "player", "partner", "kind", "value", "samples")


def _cell(value: object) -> object:
    return "" if value is None else value


def export_run(
    db_path: Path, out_dir: Path, week_ticks: int = DEFAULT_WEEK_TICKS
) -> dict[str, int]:
    """Write ``<table>.csv`` for each table and ``weekly_measures.csv``; returns rows per file.

    Everything is read in one read transaction on a read-only connection.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db = RunDB.open_readonly(Path(db_path))
    counts: dict[str, int] = {}
    try:
        conn = db._conn
        conn.execute("BEGIN")
        try:
            for table in TABLES:
                columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
                cursor = conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY id")
                name = f"{table}.csv"
                rows = 0
                with open(out_dir / name, "w", encoding="utf-8", newline="") as fh:
                    writer = csv.writer(fh)
                    writer.writerow(columns)
                    for row in cursor:
                        writer.writerow([_cell(v) for v in row])
                        rows += 1
                counts[name] = rows
            rows = 0
            with open(out_dir / WEEKLY_FILE, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(WEEKLY_COLUMNS)
                for m in weekly_measures(db, week_ticks):
                    writer.writerow(
                        [m.week, m.measure, m.player, m.partner, m.kind, _cell(m.value), m.samples]
                    )
                    rows += 1
            counts[WEEKLY_FILE] = rows
        finally:
            conn.rollback()
    finally:
        db.close()
    return counts
