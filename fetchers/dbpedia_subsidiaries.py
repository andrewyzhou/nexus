"""
Fetch public-to-public subsidiary relationships from DBpedia.

Complements fetchers/wikidata_subsidiaries.py. DBpedia is Wikipedia's
structured-data mirror — different coverage profile than Wikidata, and
in particular tends to have more recent US acquisitions that Wikidata
hasn't picked up yet (e.g. CVS→OSH, INTC→MBLY, HPE→JNPR).

Volume is small (~10–20 edges after cleanup) because DBpedia's
`dbo:symbol` / `dbp:symbol` property is sparsely populated. Use as a
merge input to the Wikidata output, not a standalone source.

Output schema matches the seeder:
    [{"ticker": "PARENT", "name": "...", "subsidiaries": ["CHILD1", ...]}]

Usage:
    python fetchers/dbpedia_subsidiaries.py
    python fetchers/dbpedia_subsidiaries.py --out out/dbpedia_subsidiaries.json --upload-s3
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import requests

DBPEDIA_ENDPOINT = "https://dbpedia.org/sparql"
USER_AGENT = "nexus-ipick/0.1 (https://github.com/andrewyzhou/nexus) requests/python"

# DBpedia uses dbo:subsidiary (parent → sub, forward). Tickers live under
# either dbo:symbol (the curated ontology property) or dbp:symbol (the
# raw-infobox property) depending on how the Wikipedia page was written,
# so we UNION both sides for recall.
SPARQL_QUERY = """
SELECT DISTINCT ?parentLabel ?parentTicker ?subLabel ?subTicker WHERE {
  ?parent dbo:subsidiary ?sub .
  { ?parent dbo:symbol ?parentTicker } UNION { ?parent dbp:symbol ?parentTicker }
  { ?sub    dbo:symbol ?subTicker    } UNION { ?sub    dbp:symbol ?subTicker }
  ?parent rdfs:label ?parentLabel . FILTER(LANG(?parentLabel) = "en")
  ?sub    rdfs:label ?subLabel    . FILTER(LANG(?subLabel)   = "en")
  FILTER(?parent != ?sub)
}
"""


def run_query() -> list[dict]:
    r = requests.get(
        DBPEDIA_ENDPOINT,
        params={"query": SPARQL_QUERY, "format": "application/sparql-results+json"},
        headers={"User-Agent": USER_AGENT},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()["results"]["bindings"]


def to_subsidiaries_json(bindings: list[dict]) -> list[dict]:
    by_parent: dict[str, set[str]] = defaultdict(set)
    name_of: dict[str, str] = {}

    for row in bindings:
        p_tkr = row["parentTicker"]["value"].upper().strip()
        s_tkr = row["subTicker"]["value"].upper().strip()

        # DBpedia tickers sometimes include exchange prefixes ("NASDAQ: GOOGL")
        # or punctuation. Keep the last colon-separated segment and trim.
        p_tkr = p_tkr.split(":")[-1].strip()
        s_tkr = s_tkr.split(":")[-1].strip()

        if not p_tkr or not s_tkr or p_tkr == s_tkr:
            continue
        if p_tkr.isdigit() or s_tkr.isdigit():
            # Non-US exchanges we don't have in our companies table
            continue

        by_parent[p_tkr].add(s_tkr)
        if p_tkr not in name_of:
            name_of[p_tkr] = row["parentLabel"]["value"]

    return [
        {"ticker": parent, "name": name_of.get(parent), "subsidiaries": sorted(subs)}
        for parent, subs in sorted(by_parent.items())
    ]


def maybe_upload_s3(path: Path) -> None:
    import shutil
    import subprocess
    target = "s3://ipickai-storage/metadata/dbpedia_subsidiaries.json"
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
        print(f"!! S3 upload skipped ({e}). Manual: aws s3 cp {path} {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="out/dbpedia_subsidiaries.json")
    parser.add_argument("--upload-s3", action="store_true")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Querying DBpedia ({DBPEDIA_ENDPOINT})...")
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
