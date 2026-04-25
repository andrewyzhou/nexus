#!/usr/bin/env python3
"""
Apply ai/pipeline/track_descriptions.json to investment_tracks.description.

Idempotent. Run after `generate_track_descriptions.py`, or let `seed_prod.py`
call it automatically as part of a fresh seed.

    python3 backend/db/load_track_descriptions.py
    python3 backend/db/load_track_descriptions.py --input path/to/other.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg2

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))
from config import DATABASE_URL  # noqa: E402

DEFAULT_INPUT = REPO_ROOT / "ai" / "pipeline" / "track_descriptions.json"


def load_track_descriptions(cursor, path: Path) -> tuple[int, int, int]:
    """Apply the JSON. Returns (updated, missing_in_db, total_in_json)."""
    if not path.exists():
        print(f"  {path.name} not found at {path} — skipping description load.")
        return 0, 0, 0
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"  could not parse {path}: {e} — skipping.")
        return 0, 0, 0
    if not isinstance(data, dict):
        print(f"  {path} is not a {{name: description}} object — skipping.")
        return 0, 0, 0

    updated = 0
    missing = 0
    for track_name, desc in data.items():
        desc = (desc or "").strip()
        if not desc:
            continue
        cursor.execute(
            "UPDATE investment_tracks SET description = %s WHERE name = %s",
            (desc, track_name),
        )
        if cursor.rowcount == 0:
            missing += 1
        else:
            updated += cursor.rowcount
    return updated, missing, len(data)


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply track descriptions JSON to DB")
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    args = ap.parse_args()

    print(f"loading {args.input}")
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    upd, miss, total = load_track_descriptions(cur, args.input)
    conn.commit()
    conn.close()
    print(f"  total in JSON: {total}, updated: {upd}, missing-from-db: {miss}")


if __name__ == "__main__":
    main()
