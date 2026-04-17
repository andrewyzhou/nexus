import json
import psycopg2
from pathlib import Path
import sys
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATABASE_URL

REPO_ROOT = Path(__file__).resolve().parents[2]

# The output JSONs live in S3, not the repo. We sync them down lazily on
# first use so the repo stays ~50MB instead of ~310MB. The extractor
# scripts under sec_pipeline/**/*.py regenerate them and the S3 copies
# should be refreshed from whoever runs the pipeline.
S3_URIS = {
    "suppliers":    "s3://ipickai-storage/metadata/suppliers.json",
    "subsidiaries": "s3://ipickai-storage/metadata/subsidiaries.json",
}


def ensure_local(kind: str, local_path: Path) -> Path:
    """Make sure `local_path` exists locally. If not, pull it from S3."""
    if local_path.exists():
        return local_path

    uri = S3_URIS[kind]
    print(f"  {local_path.name} not on disk — fetching from {uri}")
    local_path.parent.mkdir(parents=True, exist_ok=True)

    import shutil, subprocess
    if shutil.which("aws"):
        try:
            subprocess.run(["aws", "s3", "cp", uri, str(local_path)], check=True)
            print(f"  downloaded via aws cli")
            return local_path
        except subprocess.CalledProcessError as e:
            print(f"  aws cli failed: {e} — falling back to boto3")
    try:
        import boto3  # type: ignore
        bucket, key = uri.replace("s3://", "").split("/", 1)
        boto3.client("s3").download_file(bucket, key, str(local_path))
        print(f"  downloaded via boto3")
        return local_path
    except Exception as e:
        raise SystemExit(
            f"Could not fetch {uri}: {e}\n"
            f"    Set up AWS credentials (`aws configure`) or re-run the\n"
            f"    sec_pipeline/{kind}/extractor.py to regenerate locally."
        )


def seed_relationships():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    # Load companies to resolve tickers and names
    cursor.execute("SELECT ticker, name FROM companies")
    companies = cursor.fetchall()

    ticker_set = {row[0] for row in companies}
    name_to_ticker = {row[1].lower(): row[0] for row in companies}

    def resolve_target(target):
        if target in ticker_set:
            return target
        target_lower = target.lower()
        if target_lower in name_to_ticker:
            return name_to_ticker[target_lower]
        return None

    suppliers_path = ensure_local(
        "suppliers",
        REPO_ROOT / "sec_pipeline" / "suppliers" / "suppliers.json",
    )
    subsidiaries_path = ensure_local(
        "subsidiaries",
        REPO_ROOT / "sec_pipeline" / "subsidiaries" / "subsidiaries.json",
    )

    inserted_suppliers = 0
    inserted_subsidiaries = 0
    skipped_unresolved = 0
    skipped_missing_source = 0

    def process_file(filepath, relation_key, rel_type):
        nonlocal inserted_suppliers, inserted_subsidiaries, skipped_unresolved, skipped_missing_source
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"Skipping {filepath} due to error: {e}")
            return

        # Support both list format [{"ticker": ..., "suppliers": [...]}]
        # and dict format {"AAPL": {"suppliers": [...]}}
        if isinstance(data, dict):
            records = [{"ticker": k, **v} for k, v in data.items()]
        else:
            records = data

        for record in records:
            source_ticker = record.get("ticker")
            if not source_ticker:
                continue

            actual_source = resolve_target(source_ticker)
            if not actual_source:
                skipped_missing_source += 1
                continue

            targets = record.get(relation_key, [])
            for target in targets:
                if target == "NONE":
                    continue
                
                actual_target = resolve_target(target)
                if not actual_target:
                    print(f"Skipping unresolved {rel_type} target for {actual_source}: '{target}'")
                    skipped_unresolved += 1
                    continue

                if actual_target == actual_source:
                    continue

                cursor.execute("""
                    INSERT INTO relationships (source_ticker, target_ticker, relationship_type)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_ticker, target_ticker, relationship_type) DO NOTHING
                """, (actual_source, actual_target, rel_type))
                
                if cursor.rowcount > 0:
                    if rel_type == "supplier":
                        inserted_suppliers += 1
                    else:
                        inserted_subsidiaries += 1

    print("Seeding suppliers...")
    process_file(suppliers_path, "suppliers", "supplier")

    print("\nSeeding subsidiaries...")
    process_file(subsidiaries_path, "subsidiaries", "subsidiary")

    conn.commit()
    cursor.close()
    conn.close()

    print("\n" + "=" * 50)
    print("SEED COMPLETE")
    print("=" * 50)
    print(f"Inserted {inserted_suppliers} supplier edges, {inserted_subsidiaries} subsidiary edges, skipped {skipped_unresolved} unresolved")
    print(f"Skipped {skipped_missing_source} records due to missing source ticker")
    print("=" * 50)

if __name__ == "__main__":
    seed_relationships()
