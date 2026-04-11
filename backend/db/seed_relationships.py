"""
Ingest the AI team's per-ticker JSON files into the relationships table.

Source: task5/SeleniumAI_Task5/final_json/<TICKER>.json
Each file has the shape:
    {
      "ticker": "NVDA",
      "related_stocks": [
        {"ticker": "MSFT", "relationship": "Competitor", "evidence": "...", "source": "..."}
      ]
    }

We rely on the foreign keys in `relationships` (source_ticker / target_ticker
both reference companies.ticker), so any related_stock whose ticker is not
already present in `companies` is skipped — call ensure_companies() first if
you need lazy hydration via yfinance.
"""
import json
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATABASE_URL

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_JSON_DIR = REPO_ROOT / "task5" / "SeleniumAI_Task5" / "final_json"


# Free-form relationship strings from the AI team -> normalized type used by frontend.
def normalize_type(rel: str) -> str:
    r = (rel or "").lower()
    if "compet" in r:
        return "competitor"
    if "suppl" in r:
        return "supplier"
    if "invest" in r or "stake" in r:
        return "investor"
    return "partnership"


def existing_tickers(cursor) -> set:
    cursor.execute("SELECT ticker FROM companies")
    return {row[0] for row in cursor.fetchall()}


def seed_relationships(conn=None):
    own_conn = conn is None
    if own_conn:
        conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    if not AI_JSON_DIR.exists():
        print(f"No AI JSON directory at {AI_JSON_DIR}, nothing to seed")
        return 0

    have = existing_tickers(cursor)
    if not have:
        print("companies table is empty — seed companies first")
        return 0

    inserted = 0
    skipped_missing = 0

    for path in sorted(AI_JSON_DIR.glob("*.json")):
        try:
            doc = json.loads(path.read_text())
        except Exception as e:
            print(f"  ! could not parse {path.name}: {e}")
            continue

        src = doc.get("ticker")
        if not src or src not in have:
            print(f"  - skipping {path.name}: source ticker {src!r} not in companies")
            continue

        for rel in doc.get("related_stocks", []):
            tgt = rel.get("ticker")
            if not tgt:
                continue
            if tgt not in have:
                skipped_missing += 1
                continue

            rel_type = normalize_type(rel.get("relationship"))
            metadata = json.dumps({
                "raw_relationship": rel.get("relationship"),
                "evidence": rel.get("evidence"),
                "source": rel.get("source"),
                "name": rel.get("name"),
            })

            cursor.execute(
                """
                INSERT INTO relationships (source_ticker, target_ticker, relationship_type, weight, metadata)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (source_ticker, target_ticker, relationship_type) DO UPDATE
                  SET metadata = EXCLUDED.metadata
                """,
                (src, tgt, rel_type, 1.0, metadata),
            )
            inserted += 1

    conn.commit()
    if own_conn:
        conn.close()

    print(f"Relationships upserted: {inserted}  (skipped {skipped_missing} unseen tickers)")
    return inserted


if __name__ == "__main__":
    seed_relationships()
