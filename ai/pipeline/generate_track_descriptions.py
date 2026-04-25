#!/usr/bin/env python3
"""
Generate AI-written descriptions for every investment track.

One-shot batch (run when iPick adds tracks or refreshes track names):
    export ANTHROPIC_API_KEY=...
    python3 ai/pipeline/generate_track_descriptions.py

Reads the live `investment_tracks` + `companies` tables, calls Claude Haiku
once per track, and writes the result to ai/pipeline/track_descriptions.json.
Resumable — re-runs skip tracks already in the JSON. Apply to the DB by
re-running `backend/db/seed_prod.py` or `backend/db/load_track_descriptions.py`.

Useful flags:
    --dry-run                 print prompts for the first 5 tracks, no API calls
    --force                   regenerate even if a description already exists
    --tracks "Cannabis,AI"    restrict to a comma-separated list of track names
    --limit 20                cap the run to N tracks (sample / cost preview)
    --model claude-haiku-...  override the default model
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import psycopg2

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "ai" / "pipeline" / "track_descriptions.json"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://nexus:nexus@localhost:5433/corporate_data",
)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


SYSTEM_PROMPT = """You write short, factual descriptions of stock investment tracks for a research dashboard.

For each track you receive, return a 2-3 sentence (40-70 word) description that explains:
1. What the track represents — the underlying business activity or thematic exposure.
2. The primary investment drivers — regulatory, technology, macro, demand, etc.

Style requirements:
- Plain prose only. No headings, bullets, or lists.
- Neutral and factual. Avoid buzzwords like "innovative", "cutting-edge", "transformative", "revolutionary".
- Reference 1-2 major constituents by name when it sharpens the picture.
- Do not write recommendations, ratings, or price predictions.
- Return ONLY the description text. No preamble, no surrounding quotes."""


def load_existing(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))
    tmp.replace(path)


def fetch_tracks(conn, requested: set[str] | None) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.name,
               c.ticker, c.name, c.sector, c.industry, c.market_cap
        FROM investment_tracks t
        JOIN company_tracks ct ON ct.track_id = t.id
        JOIN companies c ON c.id = ct.company_id
        ORDER BY t.name, COALESCE(c.market_cap, 0) DESC
        """
    )
    by_track: dict[str, list[dict]] = {}
    for tname, ticker, cname, sector, industry, mcap in cur.fetchall():
        if requested and tname not in requested:
            continue
        by_track.setdefault(tname, []).append({
            "ticker": ticker,
            "name": cname,
            "sector": sector,
            "industry": industry,
            "market_cap": mcap,
        })
    return [{"name": k, "companies": v} for k, v in sorted(by_track.items())]


def fmt_cap(n) -> str:
    if not n:
        return ""
    n = float(n)
    if n >= 1e12: return f"${n/1e12:.1f}T"
    if n >= 1e9:  return f"${n/1e9:.1f}B"
    if n >= 1e6:  return f"${n/1e6:.0f}M"
    return f"${n:.0f}"


def build_prompt(track: dict) -> str:
    top = track["companies"][:8]
    lines = [
        f"Track name: {track['name']}",
        f"Number of constituent companies: {len(track['companies'])}",
        "Top constituents (by market cap):",
    ]
    for c in top:
        bits = [c["ticker"]]
        if c.get("name") and c["name"] != c["ticker"]:
            bits.append(c["name"])
        sector_industry = " / ".join(x for x in [c.get("sector"), c.get("industry")] if x)
        if sector_industry:
            bits.append(sector_industry)
        cap = fmt_cap(c.get("market_cap"))
        if cap:
            bits.append(cap)
        lines.append("  - " + " · ".join(bits))
    return "\n".join(lines)


def generate_one(client, model: str, track: dict) -> str:
    msg = client.messages.create(
        model=model,
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(track)}],
    )
    parts = []
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return " ".join(parts).strip().strip('"').strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int, default=0, help="Cap to N tracks (0 = all)")
    ap.add_argument("--tracks", default="", help="Comma-separated track names")
    ap.add_argument("--force", action="store_true", help="Regenerate existing descriptions")
    ap.add_argument("--dry-run", action="store_true", help="Print prompts only, no API calls")
    args = ap.parse_args()

    if not ANTHROPIC_API_KEY and not args.dry_run:
        sys.exit("ANTHROPIC_API_KEY is not set. Export it or pass --dry-run.")

    requested = {s.strip() for s in args.tracks.split(",") if s.strip()} or None

    print(f"connecting to {DATABASE_URL.split('@')[-1]}")
    conn = psycopg2.connect(DATABASE_URL)
    tracks = fetch_tracks(conn, requested)
    conn.close()
    print(f"  loaded {len(tracks)} track(s) from db")

    existing = load_existing(args.output)
    print(f"  existing descriptions on disk: {len(existing)}")

    todo = []
    for t in tracks:
        if not args.force and existing.get(t["name"], "").strip():
            continue
        todo.append(t)
    if args.limit:
        todo = todo[: args.limit]
    print(f"  to generate: {len(todo)}")

    if args.dry_run:
        for t in todo[:5]:
            print(f"\n--- {t['name']} ({len(t['companies'])} companies) ---")
            print(build_prompt(t))
        if len(todo) > 5:
            print(f"\n  ... and {len(todo) - 5} more")
        return

    if not todo:
        print("nothing to do.")
        return

    import anthropic  # imported lazily so --dry-run works without the SDK installed
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    start = time.time()
    failures = 0
    for i, track in enumerate(todo, 1):
        try:
            desc = generate_one(client, args.model, track)
        except Exception as e:
            failures += 1
            print(f"  [{i}/{len(todo)}] ERR {track['name']!r}: {e}")
            continue
        if not desc:
            failures += 1
            print(f"  [{i}/{len(todo)}] EMPTY {track['name']!r}")
            continue
        existing[track["name"]] = desc
        save(args.output, existing)  # incremental — survive Ctrl-C
        if i % 10 == 0 or i == len(todo):
            elapsed = time.time() - start
            rate = i / elapsed if elapsed else 0
            eta = (len(todo) - i) / rate if rate else 0
            print(f"  [{i}/{len(todo)}] {track['name'][:50]:<50}  {rate:.1f}/s, eta {eta:.0f}s")

    print(f"\ndone — wrote {args.output} ({len(existing)} total, {failures} failure(s))")


if __name__ == "__main__":
    main()
