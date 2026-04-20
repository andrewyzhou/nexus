"""
Fetch public-to-public subsidiary relationships from Wikidata.

Why: the SEC Exhibit 21.1 extractor produces lots of noise (country names,
table headers, placeholder strings) because it naively captures both
columns of the exhibit. Wikidata's structured relationships are cleaner
— we query only for pairs where BOTH parent and subsidiary have a
published ticker symbol, so there's no name-to-ticker reconciliation
to worry about.

Output schema matches what seed_supplier_subsidary.py expects:

    [
      {"ticker": "GOOGL", "subsidiaries": ["FIT", "WAZE", ...]},
      ...
    ]

Values are already tickers (not names), so the seeder's exact-ticker
match path handles them without any fuzzy resolution.

Usage:
    python fetchers/wikidata_subsidiaries.py                  # writes ./out/wikidata_subsidiaries.json
    python fetchers/wikidata_subsidiaries.py --out some/path.json
    python fetchers/wikidata_subsidiaries.py --upload-s3      # also push to ipickai-storage

Wikidata SPARQL has no API key requirement. Soft rate limit is 1 query
per 5 seconds from a given User-Agent; our one query runs in ~30s and
returns a few thousand pairs.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import requests

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"

# Be a good citizen: Wikidata asks for a descriptive User-Agent.
USER_AGENT = "nexus-ipick/0.1 (https://github.com/andrewyzhou/nexus; ops@ipick.ai) requests/python"

# Grab parent/subsidiary pairs where BOTH entities are publicly traded.
#
# We use ONLY P355 ("has subsidiary") rather than the looser P127
# ("owned by") or P749 ("parent organization"). P127 conflates real
# parent-subsidiary relationships with institutional shareholdings — if
# BlackRock holds a >5% stake in Apple, Wikidata may encode Apple as
# "owned by BlackRock" and produce an edge that isn't what we want
# here. P355 is an explicit, directional subsidiary statement that's
# much cleaner.
#
# Key detail: tickers in Wikidata are stored as qualifiers on the P414
# ("stock exchange") statement, not as a direct P249 claim. Pattern:
#     ?company p:P414 ?stmt .
#     ?stmt pq:P249 ?ticker .
SPARQL_QUERY = """
SELECT DISTINCT ?parentTicker ?subTicker ?parentLabel ?subLabel WHERE {
  ?parent wdt:P355 ?sub .
  ?parent p:P414 ?parentStmt .
  ?parentStmt pq:P249 ?parentTicker .
  ?sub p:P414 ?subStmt .
  ?subStmt pq:P249 ?subTicker .
  FILTER (?parent != ?sub)
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


def run_query() -> list[dict]:
    """Execute the SPARQL query and return the raw bindings list."""
    r = requests.get(
        WIKIDATA_ENDPOINT,
        params={"query": SPARQL_QUERY, "format": "json"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["results"]["bindings"]


def to_subsidiaries_json(bindings: list[dict]) -> list[dict]:
    """Collapse the flat (parent, sub) pair list into the seeder's schema."""
    by_parent: dict[str, set[str]] = defaultdict(set)
    name_of: dict[str, str] = {}

    for row in bindings:
        p_tkr = row["parentTicker"]["value"].upper().strip()
        s_tkr = row["subTicker"]["value"].upper().strip()

        # Wikidata sometimes stores tickers with exchange prefixes like
        # "NASDAQ: GOOGL" or with whitespace padding — strip both.
        p_tkr = p_tkr.split(":")[-1].strip()
        s_tkr = s_tkr.split(":")[-1].strip()

        # Drop tickers that are purely numeric (Tokyo, HK, etc. exchanges
        # that our companies table isn't likely to have) — keeps the
        # output focused on the US-listed universe we actually seed.
        if not p_tkr or not s_tkr or p_tkr == s_tkr:
            continue
        if p_tkr.isdigit() or s_tkr.isdigit():
            continue

        by_parent[p_tkr].add(s_tkr)
        if p_tkr not in name_of and "parentLabel" in row:
            name_of[p_tkr] = row["parentLabel"]["value"]
        if s_tkr not in name_of and "subLabel" in row:
            name_of[s_tkr] = row["subLabel"]["value"]

    return [
        {
            "ticker": parent,
            "name": name_of.get(parent),
            "subsidiaries": sorted(subs),
        }
        for parent, subs in sorted(by_parent.items())
    ]


def maybe_upload_s3(path: Path) -> None:
    """Push the output to ipickai-storage via aws cli if available."""
    import shutil
    import subprocess
    target = "s3://ipickai-storage/metadata/wikidata_subsidiaries.json"
    if shutil.which("aws"):
        print(f"Uploading {path} → {target}")
        subprocess.run(["aws", "s3", "cp", str(path), target], check=True)
        return
    try:
        import boto3  # type: ignore
        bucket, key = target.replace("s3://", "").split("/", 1)
        boto3.client("s3").upload_file(str(path), bucket, key)
        print(f"Uploaded via boto3: {target}")
    except Exception as e:
        print(f"!! S3 upload skipped ({e}). Upload manually with:")
        print(f"   aws s3 cp {path} {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="out/wikidata_subsidiaries.json",
        help="where to write the resulting JSON (default: out/wikidata_subsidiaries.json)",
    )
    parser.add_argument(
        "--upload-s3",
        action="store_true",
        help="also push the output to s3://ipickai-storage/metadata/",
    )
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Querying Wikidata ({WIKIDATA_ENDPOINT})...")
    bindings = run_query()
    print(f"  got {len(bindings)} raw (parent, sub) ticker pairs")

    records = to_subsidiaries_json(bindings)
    total_subs = sum(len(r["subsidiaries"]) for r in records)
    print(f"  collapsed into {len(records)} parents covering {total_subs} subsidiaries")

    out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False))
    print(f"Wrote {out_path}")

    if args.upload_s3:
        maybe_upload_s3(out_path)


if __name__ == "__main__":
    main()
