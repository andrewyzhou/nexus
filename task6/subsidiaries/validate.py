"""
Step 5: Validate subsidiaries.json

Checks:
1. JSON is valid and properly formatted
2. Every entry has "ticker" and "subsidiaries" fields
3. Missing relationships use ["NONE"]
4. No duplicate tickers
5. Spot-checks 5 random tickers by printing their data for manual review

Usage: python validate.py
"""

import json
import random
from pathlib import Path

OUTPUT = Path("subsidiaries.json")


def main():
    print("=== Validating subsidiaries.json ===\n")
    errors = []

    # 1. Check JSON is valid
    try:
        data = json.loads(OUTPUT.read_text())
        print("[PASS] Valid JSON")
    except json.JSONDecodeError as e:
        print(f"[FAIL] Invalid JSON: {e}")
        return
    except FileNotFoundError:
        print("[FAIL] subsidiaries.json not found. Run scraper.py then extractor.py first.")
        return

    # 2. Check structure
    if not isinstance(data, list):
        print("[FAIL] Top-level should be an array")
        return
    print(f"[PASS] Array with {len(data)} entries")

    for i, entry in enumerate(data):
        if "ticker" not in entry:
            errors.append(f"  Entry {i}: missing 'ticker' field")
        if "subsidiaries" not in entry:
            errors.append(f"  Entry {i}: missing 'subsidiaries' field")
        elif not isinstance(entry["subsidiaries"], list):
            errors.append(f"  Entry {i} ({entry.get('ticker')}): 'subsidiaries' is not an array")
        elif len(entry["subsidiaries"]) == 0:
            errors.append(f"  Entry {i} ({entry.get('ticker')}): empty array (should be [\"NONE\"])")

    if errors:
        print(f"[FAIL] {len(errors)} structural issues:")
        for e in errors:
            print(e)
    else:
        print("[PASS] All entries have correct structure")

    # 3. Check NONE handling
    none_entries = [e for e in data if e["subsidiaries"] == ["NONE"]]
    has_entries = [e for e in data if e["subsidiaries"] != ["NONE"]]
    print(f"[INFO] {len(has_entries)} tickers with subsidiaries, {len(none_entries)} with NONE")

    # 4. Check duplicates
    tickers = [e["ticker"] for e in data]
    dupes = set(t for t in tickers if tickers.count(t) > 1)
    if dupes:
        print(f"[FAIL] Duplicate tickers: {dupes}")
    else:
        print("[PASS] No duplicate tickers")

    # 5. Stats
    total_subs = sum(len(e["subsidiaries"]) for e in has_entries)
    avg = total_subs / len(has_entries) if has_entries else 0
    print(f"[INFO] Total subsidiaries extracted: {total_subs}")
    print(f"[INFO] Average per company: {avg:.1f}")

    # 6. Spot-check 5 random tickers
    print(f"\n=== Spot-Check (5 random tickers) ===")
    print("Compare these against actual SEC Exhibit 21.1 filings:\n")

    sample = random.sample(has_entries, min(5, len(has_entries)))
    for entry in sample:
        ticker = entry["ticker"]
        subs = entry["subsidiaries"]
        print(f"  {ticker}: {len(subs)} subsidiaries")
        for s in subs[:8]:
            print(f"    - {s}")
        if len(subs) > 8:
            print(f"    ... and {len(subs) - 8} more")
        print(f"    Verify: https://efts.sec.gov/LATEST/search-index?q=%22exhibit+21%22&forms=10-K&ticker={ticker}")
        print()

    print("=== Validation Complete ===")


if __name__ == "__main__":
    main()
