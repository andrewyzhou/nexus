import json
import re
import psycopg2
from collections import Counter
from pathlib import Path
import sys
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATABASE_URL

# ── SEC Exhibit 21.1 noise filter ───────────────────────────────────────
#
# The subsidiaries extractor pulls BOTH columns of the Exhibit 21.1 table
# (entity name + jurisdiction of incorporation), so country names,
# US state names, and the literal table header "Entity Name" show up as
# fake subsidiary entries under almost every parent. The resolver then
# substring-matches these single-word strings to real tickers and
# produces garbage edges like "Cadence Design Systems → National Bank
# of Greece".
#
# Two-layer defense: a hard-coded denylist for the obvious offenders,
# plus a frequency cap (a target legitimately owned by >N distinct
# parents is almost certainly boilerplate, not a real relationship).
_NOISE_DENYLIST_LOWER = {
    # Placeholder / header noise
    "none", "", "entity name", "jurisdiction", "jurisdiction of incorporation",
    "name of subsidiary", "subsidiary", "significant subsidiaries",
    "n/a", "not applicable",

    # Countries (Exhibit 21.1 jurisdiction column)
    "united states", "united kingdom", "united arab emirates",
    "argentina", "australia", "austria", "belgium", "brazil",
    "bulgaria", "canada", "chile", "china", "colombia", "costa rica",
    "croatia", "czech republic", "denmark", "egypt", "estonia",
    "finland", "france", "germany", "greece", "hong kong", "hungary",
    "iceland", "india", "indonesia", "ireland", "israel", "italy",
    "japan", "jordan", "kenya", "korea", "south korea", "north korea",
    "latvia", "lebanon", "lithuania", "luxembourg", "malaysia",
    "malta", "mexico", "morocco", "netherlands", "new zealand",
    "nigeria", "norway", "oman", "pakistan", "panama", "peru",
    "philippines", "poland", "portugal", "puerto rico", "qatar",
    "romania", "russia", "saudi arabia", "singapore", "slovakia",
    "slovenia", "south africa", "spain", "sri lanka", "sweden",
    "switzerland", "taiwan", "thailand", "turkey", "ukraine",
    "uruguay", "venezuela", "vietnam",

    # Continents / regions
    "europe", "asia", "africa", "north america", "south america",
    "latin america", "middle east", "caribbean",

    # Common offshore / incorporation jurisdictions
    "bermuda", "cayman islands", "british virgin islands",
    "channel islands", "isle of man", "jersey", "guernsey",

    # US states + DC (common as the jurisdiction column for US subs)
    "alabama", "alaska", "arizona", "arkansas", "california",
    "colorado", "connecticut", "delaware", "florida", "georgia",
    "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas",
    "kentucky", "louisiana", "maine", "maryland", "massachusetts",
    "michigan", "minnesota", "mississippi", "missouri", "montana",
    "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
    "new york", "north carolina", "north dakota", "ohio", "oklahoma",
    "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia",

    # Misc truncation artifacts we saw in the data
    "argenti",
}

# A target name that appears under more than this many distinct parent
# companies is treated as boilerplate noise and dropped even if it
# isn't in the denylist above. Tune if you see real relationships
# getting filtered out.
MAX_PARENTS_PER_TARGET = 5

# Corporate suffixes to strip during normalization (order matters — longer
# multi-word forms before single-word ones to avoid partial stripping).
_CORP_SUFFIXES = re.compile(
    r'\b(?:incorporated|corporation|holdings|limited|company|group|'
    r'inc|corp|co|ltd|llc|lp|plc|ag|nv|sa|spa|pty|holding)\b',
    re.IGNORECASE,
)
# Dotted abbreviations like "n.v.", "s.a.", "s.p.a." — collapse before punct strip.
_DOTTED_ABBREV = re.compile(r'\b((?:[a-z]\.){2,})', re.IGNORECASE)
_PUNCT = re.compile(r'[.,&\'()]')
_WS    = re.compile(r'\s+')


def _normalize(name: str) -> str:
    """Lowercase, strip punctuation, remove corporate suffixes, collapse whitespace."""
    s = name.lower()
    # Collapse dotted abbreviations (e.g. "n.v." → "nv", "s.p.a." → "spa")
    # before the general punctuation pass so they match suffix patterns.
    s = _DOTTED_ABBREV.sub(lambda m: m.group(1).replace('.', ''), s)
    s = _PUNCT.sub(' ', s)
    s = _CORP_SUFFIXES.sub(' ', s)
    s = _WS.sub(' ', s).strip()
    return s

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

    # Normalized name index: normalized_name → ticker.
    # When multiple companies normalize to the same string, store None to
    # mark the collision so we never silently pick the wrong one.
    norm_to_ticker: dict[str, str | None] = {}
    for ticker, name in companies:
        norm = _normalize(name)
        if not norm:
            continue
        if norm in norm_to_ticker:
            norm_to_ticker[norm] = None   # collision — mark ambiguous
        else:
            norm_to_ticker[norm] = ticker

    # Resolution counters (one list so the nested closure can mutate them).
    _counts = [0, 0, 0, 0]  # [exact_ticker, exact_name, norm_name, substring]

    def resolve_target(target):
        # 1. Exact ticker match
        if target in ticker_set:
            _counts[0] += 1
            return target

        target_lower = target.lower()

        # 2. Exact lowercase name match
        if target_lower in name_to_ticker:
            _counts[1] += 1
            return name_to_ticker[target_lower]

        target_norm = _normalize(target)
        if not target_norm:
            return None

        # 3. Normalized-name exact match
        if target_norm in norm_to_ticker and norm_to_ticker[target_norm] is not None:
            _counts[2] += 1
            return norm_to_ticker[target_norm]

        # 4. Substring match (name-on-name only, no tickers).
        #    Accept only if exactly one candidate matches to avoid ambiguity.
        matches = []
        for norm, tkr in norm_to_ticker.items():
            if tkr is None:
                continue
            if target_norm in norm or norm in target_norm:
                matches.append(tkr)
        if len(matches) == 1:
            _counts[3] += 1
            return matches[0]

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
    skipped_noise = 0

    def process_file(filepath, relation_key, rel_type):
        nonlocal inserted_suppliers, inserted_subsidiaries, skipped_unresolved, skipped_missing_source, skipped_noise
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

        # Pre-pass: count how many DISTINCT parents list each target. A
        # target appearing under >MAX_PARENTS_PER_TARGET distinct parents
        # is treated as boilerplate noise regardless of what it is.
        target_parent_count: dict[str, set] = {}
        for record in records:
            src = record.get("ticker")
            if not src:
                continue
            for t in record.get(relation_key, []):
                if not t:
                    continue
                target_parent_count.setdefault(t, set()).add(src)

        noisy_by_frequency = {
            t for t, parents in target_parent_count.items()
            if len(parents) > MAX_PARENTS_PER_TARGET
        }
        if noisy_by_frequency:
            # Only log the top 10 offenders so we can see what we're dropping
            top = sorted(noisy_by_frequency,
                         key=lambda t: -len(target_parent_count[t]))[:10]
            print(f"  [{rel_type}] frequency filter: dropping {len(noisy_by_frequency)} "
                  f"targets that appear under >{MAX_PARENTS_PER_TARGET} distinct parents")
            for t in top:
                print(f"    {len(target_parent_count[t]):5d}× {t!r}")

        def is_noise(target: str) -> bool:
            if not target:
                return True
            if target.strip().lower() in _NOISE_DENYLIST_LOWER:
                return True
            if target in noisy_by_frequency:
                return True
            return False

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
                if is_noise(target):
                    skipped_noise += 1
                    continue

                actual_target = resolve_target(target)
                if not actual_target:
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

    print("\n" + "=" * 54)
    print("SEED COMPLETE")
    print("=" * 54)
    print(f"Inserted {inserted_suppliers} supplier edges, {inserted_subsidiaries} subsidiary edges")
    print(f"\nResolution breakdown:")
    print(f"  Resolved by exact ticker:        {_counts[0]}")
    print(f"  Resolved by exact name:          {_counts[1]}")
    print(f"  Resolved by normalized name:     {_counts[2]}")
    print(f"  Resolved by substring match:     {_counts[3]}")
    print(f"  Skipped unresolved:              {skipped_unresolved}")
    print(f"  Skipped missing source ticker:   {skipped_missing_source}")
    print(f"  Skipped SEC noise (jurisdictions/boilerplate): {skipped_noise}")
    print("=" * 54)

if __name__ == "__main__":
    seed_relationships()
