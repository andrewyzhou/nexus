"""
Export the Nexus database to a structured JSON snapshot and optionally upload
it to S3 under s3://ipickai-storage/backups/.

File naming: backups/nexus_v{YYYYMMDD}_{HHMMSS}.json
  e.g. backups/nexus_v20260427_143022.json

Usage:
    python backend/db/db_to_json.py                  # dump to stdout / local file
    python backend/db/db_to_json.py --upload          # dump + push to S3
    python backend/db/db_to_json.py --out snapshot.json          # custom local path
    python backend/db/db_to_json.py --upload --out /tmp/snap.json  # both

Output schema:
    {
      "meta": { "exported_at": "<ISO datetime>", "counts": {...} },
      "companies": [...],
      "tracks": [...],          // each track has a "companies" list of tickers
      "relationships": [...]
    }
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATABASE_URL

S3_BUCKET = "ipickai-storage"
S3_PREFIX = "backups"


def export_db(conn) -> dict:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT ticker, name, exchange, country, sector, industry, currency,
               price, market_cap, enterprise_value, pe_ratio, eps,
               employees, website, description
        FROM companies
        ORDER BY ticker
    """)
    companies = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT id, name, description FROM investment_tracks ORDER BY name")
    raw_tracks = cur.fetchall()

    cur.execute("""
        SELECT it.id AS track_id, c.ticker
        FROM company_tracks ct
        JOIN companies c ON c.id = ct.company_id
        JOIN investment_tracks it ON it.id = ct.track_id
        ORDER BY it.name, c.ticker
    """)
    track_tickers: dict[int, list[str]] = {}
    for row in cur.fetchall():
        track_tickers.setdefault(row["track_id"], []).append(row["ticker"])

    tracks = []
    for t in raw_tracks:
        tracks.append({
            "id": t["id"],
            "name": t["name"],
            "description": t["description"],
            "companies": track_tickers.get(t["id"], []),
        })

    cur.execute("""
        SELECT source_ticker, target_ticker, relationship_type, weight, metadata
        FROM relationships
        ORDER BY source_ticker, target_ticker, relationship_type
    """)
    relationships = [dict(r) for r in cur.fetchall()]

    return {
        "meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "counts": {
                "companies": len(companies),
                "tracks": len(tracks),
                "relationships": len(relationships),
            },
        },
        "companies": companies,
        "tracks": tracks,
        "relationships": relationships,
    }


def s3_key(dt: datetime) -> str:
    return f"{S3_PREFIX}/nexus_v{dt.strftime('%Y%m%d_%H%M%S')}.json"


def upload_to_s3(data: str, key: str) -> None:
    import shutil
    import subprocess

    if shutil.which("aws"):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(data)
            tmp = f.name
        try:
            subprocess.run(
                ["aws", "s3", "cp", tmp, f"s3://{S3_BUCKET}/{key}",
                 "--content-type", "application/json"],
                check=True,
            )
            print(f"  uploaded via aws cli → s3://{S3_BUCKET}/{key}")
            return
        finally:
            Path(tmp).unlink(missing_ok=True)

    try:
        import boto3  # type: ignore
        boto3.client("s3").put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=data.encode(),
            ContentType="application/json",
        )
        print(f"  uploaded via boto3 → s3://{S3_BUCKET}/{key}")
    except Exception as e:
        print(f"  ! S3 upload failed: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Nexus DB to JSON")
    parser.add_argument("--upload", action="store_true", help="Upload snapshot to S3")
    parser.add_argument("--out", metavar="PATH", help="Write JSON to this local path")
    args = parser.parse_args()

    print("Connecting to database…")
    conn = psycopg2.connect(DATABASE_URL)
    snapshot = export_db(conn)
    conn.close()

    m = snapshot["meta"]
    print(
        f"Exported: {m['counts']['companies']} companies, "
        f"{m['counts']['tracks']} tracks, "
        f"{m['counts']['relationships']} relationships"
    )

    payload = json.dumps(snapshot, indent=2, default=str)

    now = datetime.now(timezone.utc)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(payload)
        print(f"  written → {out_path}")
    elif not args.upload:
        # Default: write locally next to this script with a versioned name
        out_path = Path(__file__).parent / f"nexus_v{now.strftime('%Y%m%d_%H%M%S')}.json"
        out_path.write_text(payload)
        print(f"  written → {out_path}")

    if args.upload:
        key = s3_key(now)
        print(f"Uploading to S3…")
        upload_to_s3(payload, key)


if __name__ == "__main__":
    main()
