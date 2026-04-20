"""
Fetch parent-subsidiary relationships from OpenCorporates.

Why: complements the Wikidata fetcher. OpenCorporates has broader
coverage of private/mid-cap subs that Wikidata misses. Costs rate-limit
budget though: ~2 API calls per ticker (search + detail), so 4,400
tickers ≈ 9,000 calls. The free tier is 500 calls/month; the Public
Data plan ($59/mo) is 5,000/mo. Plan your cap accordingly.

What it does:
  1. For each ticker in the input list, search OpenCorporates by name
     (from a ticker → name map, usually from a prior yfinance seed).
  2. Pick the best match (prefer the jurisdiction with the largest
     number of matching identifier_uids, fall back to first result).
  3. GET the company's full record, extract `controlling_entity` +
     `ultimate_controlling_company`.
  4. Record an inverted edge: if our ticker X has controlling_entity Y,
     the graph edge is Y → X with relationship_type = "subsidiary"
     (parent → child, matching the schema the seeder expects).

Output schema matches seed_supplier_subsidary.py:

    [
      {"ticker": "PARENT_TKR", "subsidiaries": ["CHILD_TKR", ...]},
      ...
    ]

The script is resumable — it writes its checkpoint after each batch and
will skip tickers already present in the output file on the next run.

Usage:
    export OPENCORPORATES_API_KEY=oc_xxxxxxxx
    python fetchers/opencorporates_relationships.py \\
        --tickers-json out/wikidata_subsidiaries.json \\
        --limit 200 \\
        --out out/opencorporates_subsidiaries.json

    # or feed it tickers from a plain list + a name map
    python fetchers/opencorporates_relationships.py \\
        --tickers-file scraper/basket_tickers.txt \\
        --names-json some/ticker_to_name.json \\
        --out out/opencorporates_subsidiaries.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

OC_API = "https://api.opencorporates.com/v0.4"

# Delay between API calls (seconds). OpenCorporates doesn't publish a
# hard per-second limit for paid tiers, but being polite avoids throttle
# responses on bulk runs.
DEFAULT_SLEEP_SEC = 0.5


class RateLimited(Exception):
    pass


def oc_get(path: str, params: dict | None = None, api_key: str | None = None,
           timeout: int = 30) -> dict:
    """Thin wrapper around requests.get with error handling."""
    params = dict(params or {})
    if api_key:
        params["api_token"] = api_key
    r = requests.get(f"{OC_API}{path}", params=params, timeout=timeout)
    if r.status_code == 429:
        raise RateLimited(r.text)
    if r.status_code >= 400:
        raise RuntimeError(f"OC {path} → {r.status_code}: {r.text[:200]}")
    return r.json()


def search_company(name: str, api_key: str | None) -> dict | None:
    """Return the best-match company record for a given legal name."""
    resp = oc_get(
        "/companies/search",
        {
            "q": name,
            "per_page": 10,
            "order": "score",
            "inactive": "false",
            "normalise_company_name": "true",
        },
        api_key=api_key,
    )
    companies = resp.get("results", {}).get("companies", [])
    if not companies:
        return None
    # Prefer US jurisdictions (broadest for our ticker universe), then by
    # rank-order from ElasticSearch. OC returns them score-ordered when
    # order=score is passed.
    companies.sort(
        key=lambda c: (
            0 if c["company"].get("jurisdiction_code", "").startswith("us") else 1,
            0 if c["company"].get("current_status") == "Active" else 1,
        )
    )
    return companies[0]["company"]


def get_company_detail(jurisdiction: str, number: str,
                       api_key: str | None) -> dict | None:
    """GET full record for one company (includes controlling_entity)."""
    try:
        resp = oc_get(
            f"/companies/{jurisdiction}/{number}",
            {"sparse": "false"},
            api_key=api_key,
        )
    except RuntimeError as e:
        # 404 for companies sometimes returned as 403 — swallow
        print(f"  !! detail fetch failed: {e}", file=sys.stderr)
        return None
    return resp.get("results", {}).get("company")


def load_ticker_name_map(args: argparse.Namespace) -> dict[str, str]:
    """Build the ticker → legal name map from whichever input was given."""
    m: dict[str, str] = {}
    if args.tickers_json:
        # Expect the Wikidata output shape — has both ticker and name.
        data = json.loads(Path(args.tickers_json).read_text())
        for rec in data:
            if rec.get("ticker") and rec.get("name"):
                m[rec["ticker"].upper()] = rec["name"]
            for sub_tkr in rec.get("subsidiaries", []):
                m.setdefault(sub_tkr.upper(), sub_tkr)  # placeholder name
    if args.names_json:
        m.update({k.upper(): v for k, v in
                  json.loads(Path(args.names_json).read_text()).items()})
    if args.tickers_file:
        # Plain list — we don't have a name, so use the ticker as a
        # fallback query string. OC search tolerates this for big names
        # but won't work great for obscure tickers.
        for line in Path(args.tickers_file).read_text().splitlines():
            t = line.strip().upper()
            if t:
                m.setdefault(t, t)
    if not m:
        raise SystemExit(
            "No tickers provided. Pass --tickers-json, --tickers-file, or --names-json."
        )
    return m


def load_checkpoint(out_path: Path) -> tuple[dict[str, set[str]], set[str]]:
    """Load existing parent→subs map + the set of tickers already processed."""
    if not out_path.exists():
        return defaultdict(set), set()
    try:
        existing = json.loads(out_path.read_text())
    except json.JSONDecodeError:
        return defaultdict(set), set()

    by_parent: dict[str, set[str]] = defaultdict(set)
    processed: set[str] = set()
    for rec in existing:
        parent = rec["ticker"]
        subs = rec.get("subsidiaries", [])
        by_parent[parent].update(subs)
        # Each entry in the output means we processed its `ticker`.
        processed.add(parent)
        # We also mark all *subsidiaries* as "already seen as a result" —
        # but NOT as "processed" (we still need to query them for their
        # own parent chain). Keep this distinction explicit.
    return by_parent, processed


def write_checkpoint(out_path: Path, by_parent: dict[str, set[str]]) -> None:
    records = [
        {"ticker": p, "subsidiaries": sorted(subs)}
        for p, subs in sorted(by_parent.items())
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers-json", help="JSON in the wikidata_subsidiaries format (uses ticker+name)")
    parser.add_argument("--tickers-file", help="plain ticker list, one per line")
    parser.add_argument("--names-json",  help='JSON mapping {"TICKER": "Legal Name", ...}')
    parser.add_argument("--out", default="out/opencorporates_subsidiaries.json",
                        help="where to write / resume (default: out/opencorporates_subsidiaries.json)")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the number of new tickers processed this run (for rate-limit budget)")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SEC,
                        help=f"seconds between API calls (default {DEFAULT_SLEEP_SEC})")
    parser.add_argument("--upload-s3", action="store_true",
                        help="push result to s3://ipickai-storage/metadata/ at the end")
    args = parser.parse_args()

    api_key = os.environ.get("OPENCORPORATES_API_KEY")
    if not api_key:
        print("!! OPENCORPORATES_API_KEY not set — the free endpoint has a 500-call/month cap", file=sys.stderr)

    ticker_to_name = load_ticker_name_map(args)
    print(f"Loaded {len(ticker_to_name)} tickers to query")

    out_path = Path(args.out)
    by_parent, processed = load_checkpoint(out_path)
    to_process = [t for t in ticker_to_name if t not in processed]
    if args.limit:
        to_process = to_process[: args.limit]

    print(f"Resuming: {len(processed)} already processed, {len(to_process)} to go "
          f"({'capped by --limit' if args.limit else 'full run'})")

    try:
        for i, ticker in enumerate(to_process, 1):
            name = ticker_to_name[ticker]
            try:
                hit = search_company(name, api_key)
                time.sleep(args.sleep)
                if not hit:
                    print(f"  [{i}/{len(to_process)}] {ticker}: no OC match for {name!r}")
                    processed.add(ticker)
                    continue

                detail = get_company_detail(
                    hit["jurisdiction_code"], hit["company_number"], api_key
                )
                time.sleep(args.sleep)
                processed.add(ticker)

                if not detail:
                    continue

                parent = detail.get("controlling_entity") or {}
                parent_name = parent.get("name") if isinstance(parent, dict) else None
                if not parent_name:
                    # No known parent — not a subsidiary of anyone tracked
                    continue

                # Match the parent name back to a ticker in our known universe.
                # Simple case-insensitive exact match against ticker_to_name.
                parent_ticker = None
                norm = parent_name.strip().lower()
                for tkr, nm in ticker_to_name.items():
                    if nm and nm.strip().lower() == norm:
                        parent_ticker = tkr
                        break
                if not parent_ticker:
                    # Parent is probably a private/foreign entity we don't
                    # track — OC-only parents aren't useful for our graph.
                    continue

                by_parent[parent_ticker].add(ticker)
                print(f"  [{i}/{len(to_process)}] {ticker} parent → {parent_ticker} ({parent_name})")

            except RateLimited as e:
                print(f"\n!! Rate-limited on {ticker}: {e}", file=sys.stderr)
                print(f"   Checkpoint written to {out_path}. Re-run later to continue.")
                break
            except Exception as e:
                print(f"  [{i}/{len(to_process)}] {ticker}: {e}", file=sys.stderr)
                continue

            # Periodic checkpoint — don't lose progress on Ctrl+C
            if i % 25 == 0:
                write_checkpoint(out_path, by_parent)
    finally:
        write_checkpoint(out_path, by_parent)

    parent_count = len(by_parent)
    total_subs = sum(len(s) for s in by_parent.values())
    print(f"\nDone. {parent_count} parents, {total_subs} subsidiary edges → {out_path}")

    if args.upload_s3:
        import shutil
        import subprocess
        target = "s3://ipickai-storage/metadata/opencorporates_subsidiaries.json"
        if shutil.which("aws"):
            subprocess.run(["aws", "s3", "cp", str(out_path), target], check=True)
            print(f"Uploaded → {target}")
        else:
            print(f"!! aws cli not found. Upload manually with:\n   aws s3 cp {out_path} {target}")


if __name__ == "__main__":
    main()
