"""
Merge multiple subsidiary JSON files into one, preserving per-edge provenance.

Each input is expected in the seeder's shape:
    [{"ticker": "PARENT", "subsidiaries": ["CHILD1", "CHILD2", ...]}]

The merged output keeps the same shape (so the seeder doesn't need to
change), but also writes a sidecar `*.provenance.json` that records
which source(s) contributed each edge — useful for auditing and for
weighting edges by confidence later.

Usage:
    python fetchers/merge_subsidiaries.py \\
        out/wikidata_subsidiaries.json:wikidata \\
        out/dbpedia_subsidiaries.json:dbpedia \\
        --out out/merged_subsidiaries.json

    # Each positional arg is PATH:SOURCE_LABEL
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+",
                        help="PATH:LABEL entries, e.g. out/wikidata.json:wikidata")
    parser.add_argument("--out", default="out/merged_subsidiaries.json")
    args = parser.parse_args()

    # { parent_ticker: { child_ticker: set(source_labels) } }
    edges: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    name_of: dict[str, str] = {}

    for spec in args.inputs:
        if ":" not in spec:
            raise SystemExit(f"input spec {spec!r} missing :LABEL suffix")
        path_str, label = spec.rsplit(":", 1)
        path = Path(path_str)
        if not path.exists():
            print(f"  !! {path} does not exist — skipping")
            continue
        records = json.loads(path.read_text())
        print(f"Loading {path} (label={label}): {len(records)} parents")
        for rec in records:
            parent = rec["ticker"]
            if rec.get("name") and parent not in name_of:
                name_of[parent] = rec["name"]
            for child in rec.get("subsidiaries", []):
                edges[parent][child].add(label)

    # Write merged output in seeder shape
    merged = [
        {
            "ticker": parent,
            "name":   name_of.get(parent),
            "subsidiaries": sorted(children.keys()),
        }
        for parent, children in sorted(edges.items())
    ]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
    total_edges = sum(len(r["subsidiaries"]) for r in merged)
    print(f"\nMerged: {len(merged)} parents, {total_edges} unique edges → {out_path}")

    # Write provenance sidecar
    prov_path = out_path.with_suffix(".provenance.json")
    provenance = [
        {
            "parent": parent,
            "child":  child,
            "sources": sorted(sources),
        }
        for parent, children in sorted(edges.items())
        for child, sources in sorted(children.items())
    ]
    prov_path.write_text(json.dumps(provenance, indent=2, ensure_ascii=False))

    # Quick overlap summary so we can see how much each source contributes
    from collections import Counter
    combos = Counter(tuple(sorted(sources)) for p in edges.values() for sources in p.values())
    print("\nEdge provenance breakdown:")
    for combo, n in combos.most_common():
        print(f"  {n:5d} edges from {' + '.join(combo)}")


if __name__ == "__main__":
    main()
