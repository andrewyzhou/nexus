# Relationship fetchers

Alternative data sources for the `relationships` table, complementing (or
replacing) the SEC Exhibit 21.1 extractor in `sec_pipeline/`.

Both scripts write their output to JSON matching the schema
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

## Running order

Typical refresh:

```bash
# 1. Wikidata — always free, always first
python fetchers/wikidata_subsidiaries.py --upload-s3

# 2. OpenCorporates — expensive, use the Wikidata output as its ticker
#    universe so we have names for the OC name-search step
export OPENCORPORATES_API_KEY=oc_xxxxxxxx
python fetchers/opencorporates_relationships.py \
    --tickers-json out/wikidata_subsidiaries.json \
    --upload-s3

# 3. Re-seed the DB on the EC2 box
python backend/db/seed_supplier_subsidary.py
```
