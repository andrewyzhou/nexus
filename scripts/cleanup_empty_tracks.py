#!/usr/bin/env python3
"""
Two-part cleanup:
  1. Remove junk entries from ticker_track.json (fake tickers like ticker1, delete, etc.)
  2. Delete investment_tracks rows that have no company_tracks links from the DB

Run from repo root:
    python scripts/cleanup_empty_tracks.py

Dry-run (no writes):
    python scripts/cleanup_empty_tracks.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg2

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
from config import DATABASE_URL  # noqa: E402

TICKER_TRACK_PATH = REPO_ROOT / "ticker_track.json"

# Tickers that are clearly junk — not real stock symbols
JUNK_TICKERS = {"ticker1", "ticker2", "ticker3", "ticker4", "ticker5", "delete", "Exchange", 'Brokerage"'}


def clean_ticker_track(dry_run: bool) -> int:
    with TICKER_TRACK_PATH.open() as f:
        data = json.load(f)

    junk = {k: v for k, v in data.items() if k in JUNK_TICKERS}
    if not junk:
        print("ticker_track.json: no junk entries found")
        return 0

    print(f"ticker_track.json: removing {len(junk)} junk entries:")
    for k, v in sorted(junk.items()):
        print(f"  {k!r} -> {v!r}")

    if not dry_run:
        cleaned = {k: v for k, v in data.items() if k not in JUNK_TICKERS}
        with TICKER_TRACK_PATH.open("w") as f:
            json.dump(cleaned, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"  written ({len(cleaned)} entries remain)")

    return len(junk)


def delete_empty_tracks(dry_run: bool) -> int:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name FROM investment_tracks
        WHERE NOT EXISTS (
            SELECT 1 FROM company_tracks WHERE track_id = investment_tracks.id
        )
        ORDER BY name
    """)
    rows = cur.fetchall()

    if not rows:
        print("DB: no empty tracks found")
        conn.close()
        return 0

    print(f"DB: deleting {len(rows)} empty tracks:")
    for _, name in rows:
        print(f"  {name!r}")

    if not dry_run:
        ids = [r[0] for r in rows]
        cur.execute(
            "DELETE FROM investment_tracks WHERE id = ANY(%s)",
            (ids,),
        )
        conn.commit()
        print(f"  deleted {cur.rowcount} rows")

    conn.close()
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Print what would happen without writing")
    args = ap.parse_args()

    if args.dry_run:
        print("=== DRY RUN — no changes will be made ===\n")

    removed_tickers = clean_ticker_track(args.dry_run)
    print()
    deleted_tracks = delete_empty_tracks(args.dry_run)

    print(f"\nDone. Junk tickers removed: {removed_tickers}. Empty tracks deleted: {deleted_tracks}.")
    if args.dry_run:
        print("Re-run without --dry-run to apply.")


if __name__ == "__main__":
    main()
