import json
import psycopg2
import psycopg2.extras
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATABASE_URL
from db.init import init_db
from db.seed import create_tracks_tables, load_investment_tracks
try:
    from db.seed_supplier_subsidary import seed_relationships
except ModuleNotFoundError:
    from seed_supplier_subsidary import seed_relationships
from db.seed_prod import row_from_yahoo, INSERT_SQL

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
JSON_PATH = REPO_ROOT / "scraper" / "data" / "processed" / "stock_data.json"

def main():
    print("== Nexus live seed (From Local JSON) ==")
    if not JSON_PATH.exists():
        print(f"Error: Could not find {JSON_PATH}")
        return

    print(f"Loading data from {JSON_PATH}...")
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        results = json.load(f)

    init_db()
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    create_tracks_tables(cursor)

    rows = [r for r in (row_from_yahoo(e) for e in results) if r]
    print(f"  inserting {len(rows)} company rows...")
    psycopg2.extras.execute_values(cursor, INSERT_SQL, rows, page_size=500)
    conn.commit()

    print(f"Linking tracks...")
    unique, linked, missing = load_investment_tracks(cursor)
    conn.commit()
    print(f"  tracks={unique}  links={linked}  unmatched={missing}")

    conn.commit()
    conn.close()

    print("\nSeeding supplier + subsidiary edges from SEC filings...")
    seed_relationships()
    print("\nDone. Backend is ready to serve data.")

if __name__ == "__main__":
    main()
