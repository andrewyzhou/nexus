# Relationship fetchers

Alternative data sources for the `relationships` table, complementing (or
replacing) the SEC Exhibit 21.1 extractor in `sec_pipeline/`.

| Source | Output | Key req? | Notes |
|---|---|---|---|
| `wikidata_subsidiaries.py`    | ~580 edges  | No  | Primary. SPARQL on P355 + P414 ticker qualifiers. |
| `dbpedia_subsidiaries.py`     | ~12 edges   | No  | Supplemental. Catches recent US acquisitions Wikidata missed. |
| `opencorporates_relationships.py` | varies   | Yes | Dormant unless you have an OC API key. |
| `merge_subsidiaries.py`       | —           | —   | Unions the above into one file + writes a per-edge provenance sidecar. |

All scripts write their output to JSON matching the schema
`seed_supplier_subsidary.py` already understands:

```json
[
  {"ticker": "PARENT", "subsidiaries": ["CHILD1", "CHILD2", ...]}
]
```

Values in the `subsidiaries` array are **tickers**, not names, so the
seeder's exact-ticker match path handles them with zero fuzzy resolution
— none of the noise problems we saw with the SEC extractor.

## `wikidata_subsidiaries.py`

One SPARQL query to query.wikidata.org. Returns every (parent, subsidiary)
pair where both sides are publicly-traded (both have a ticker in
Wikidata's P249 property). Takes ~30 seconds end-to-end and is free.

```bash
python fetchers/wikidata_subsidiaries.py
python fetchers/wikidata_subsidiaries.py --out out/wikidata_subsidiaries.json --upload-s3
```

Output covers well-known public parents (Alphabet, Berkshire, J&J, etc.)
but has thin coverage for smaller / foreign issuers. Good precision,
moderate recall.

No API key required.

## `opencorporates_relationships.py`

Hits the OpenCorporates v0.4 API for every ticker: searches by company
name, grabs the top match, reads its `controlling_entity` to infer a
parent. Broader coverage than Wikidata (especially for mid-caps and
foreign subs), but rate-limited:

| Plan | Calls/month | ~ tickers/run (2 calls each) |
|---|---|---|
| Free | 500 | 250 |
| Public Data ($59/mo) | 5,000 | 2,500 |
| Premium | 10,000+ | 5,000+ |

The script is **resumable** — checkpoints the output after every 25 tickers,
so a 429 or Ctrl+C doesn't lose progress. Re-run to continue.

```bash
export OPENCORPORATES_API_KEY=oc_xxxxxxxx

# Seed the ticker list from the Wikidata output (which already has names)
python fetchers/opencorporates_relationships.py \
    --tickers-json out/wikidata_subsidiaries.json \
    --limit 200 \
    --out out/opencorporates_subsidiaries.json

# Or from a plain ticker list
python fetchers/opencorporates_relationships.py \
    --tickers-file scraper/basket_tickers.txt \
    --out out/opencorporates_subsidiaries.json
```

Add `--upload-s3` to push the final JSON up to `ipickai-storage/metadata/`.

## Integrating with the seeder

Once you have `out/wikidata_subsidiaries.json` (and optionally the OC
output), three options:

1. **Upload to S3, update `S3_URIS` in `seed_supplier_subsidary.py`** to
   pull these keys instead of / in addition to the SEC `subsidiaries.json`.
2. **Merge the two JSONs manually** into a combined `subsidiaries.json`
   and upload to S3 under the existing key.
3. **Keep as a parallel data source** and have the seeder union all
   three files in memory before inserting.

Option 1 is cleanest; a follow-up PR can wire it in.

## `dbpedia_subsidiaries.py`

One SPARQL query to dbpedia.org. Reads `dbo:subsidiary` statements and
cross-references with `dbo:symbol` / `dbp:symbol` for tickers on both
sides. Covers a different slice than Wikidata — notably recent US
acquisitions (e.g. CVS → Oak Street Health, INTC → MBLY, HPE → JNPR)
that Wikidata hasn't ingested yet.

Output is small (~10–20 edges after cleanup) because DBpedia's symbol
fields are sparsely populated. Don't use as a standalone source — it's
only worth running as a supplement to Wikidata.

No API key required.

```bash
python fetchers/dbpedia_subsidiaries.py
```

## `merge_subsidiaries.py`

Takes multiple fetcher outputs and produces one combined file in the
same seeder schema, plus a `*.provenance.json` sidecar recording which
source(s) contributed each edge. Edges that appear in multiple sources
are strong candidates for high-confidence weighting.

```bash
python fetchers/merge_subsidiaries.py \
    out/wikidata_subsidiaries.json:wikidata \
    out/dbpedia_subsidiaries.json:dbpedia \
    --out out/merged_subsidiaries.json
```

The per-positional syntax is `PATH:SOURCE_LABEL`. Example output:

```
Merged: 367 parents, 589 unique edges → out/merged_subsidiaries.json

Edge provenance breakdown:
    577 edges from wikidata
      9 edges from dbpedia
      3 edges from dbpedia + wikidata   ← cross-validated, highest confidence
```

## Running order

Typical refresh:

```bash
# 1. Wikidata — primary, free, always first
python fetchers/wikidata_subsidiaries.py

# 2. DBpedia — supplemental, free
python fetchers/dbpedia_subsidiaries.py

# 3. (Optional) OpenCorporates — only if you have a paid key
export OPENCORPORATES_API_KEY=oc_xxxxxxxx
python fetchers/opencorporates_relationships.py \
    --tickers-json out/wikidata_subsidiaries.json

# 4. Merge into a single file
python fetchers/merge_subsidiaries.py \
    out/wikidata_subsidiaries.json:wikidata \
    out/dbpedia_subsidiaries.json:dbpedia \
    --out out/merged_subsidiaries.json

# 5. Upload the merged file to S3 under the key the seeder expects
aws s3 cp out/merged_subsidiaries.json \
    s3://ipickai-storage/metadata/subsidiaries.json

# 6. Re-seed the DB on the EC2 box
python backend/db/seed_supplier_subsidary.py
```
