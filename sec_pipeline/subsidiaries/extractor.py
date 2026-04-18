"""
Step 2+3: Extract subsidiaries from raw Exhibit 21.1 text and format to JSON.

Reads from raw_exhibits/<TICKER>.txt (output of scraper.py)
Writes to subsidiaries.json

Default: Uses Ollama LLM for extraction (same as selenium_nexus.ipynb Cell 4).
         Falls back to regex if Ollama is not running.

Setup (same as selenium_nexus.ipynb):
    ollama pull llama3.2
    ollama serve          # keep running in another terminal

Usage:
    python extractor.py                
    python extractor.py --llm regex    
    python extractor.py --llm openai   
    python extractor.py --llm anthropic 
"""

import json
import re
import os
import sys
import argparse
from pathlib import Path

import requests

# Try importing Ollama (same as selenium_nexus.ipynb Cell 0)
try:
    import ollama as _ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

RAW_DIR = Path("raw_exhibits")
OUTPUT = Path("subsidiaries.json")
TICKERS_FILE = "tickers.txt"

# LLM config (from selenium_nexus.ipynb Cell 4)
LLM_MODEL = "llama3.2"  # same model as notebook


# ============================================================
# Step 2: LLM Subsidiary Extraction Prompts
# ============================================================
# Strict, highly specific prompts for extracting subsidiary names
# from Exhibit 21.1 text. Designed to minimize hallucinations.

SYSTEM_PROMPT = (
    "You are a financial data extraction tool. You extract subsidiary "
    "company names from SEC Exhibit 21.1 filings. You respond ONLY in "
    "strict JSON format. You NEVER hallucinate or invent data."
)

USER_PROMPT_TEMPLATE = """Read the following Exhibit 21.1 text from an SEC 10-K filing
and extract all subsidiary company names.

Rules:
- Return ONLY a valid JSON array of subsidiary name strings
- Remove legal suffixes like LLC, Inc., Ltd., Corp., L.P., S.A., GmbH,
  B.V., Pte., Limited, N.A., plc UNLESS they help distinguish two entities
- If zero subsidiaries found, return ["NONE"]
- Do NOT hallucinate - ONLY list entities explicitly named in the text
- Do NOT include the parent company itself
- Do NOT include jurisdictions of incorporation

Exhibit 21.1 Text:
{text}

Respond with ONLY the JSON array, nothing else:"""


def load_tickers():
    return [t.strip().upper() for t in Path(TICKERS_FILE).read_text().splitlines() if t.strip()]


# ============================================================
# Ollama LLM Extraction (default — matches selenium_nexus.ipynb)
# ============================================================

def extract_ollama(raw_text, ticker):
    """
    Use Ollama to extract subsidiaries. Same pattern as selenium_nexus.ipynb
    Cell 4: call_llm() using _ollama.chat() with json format.
    Falls back to regex if Ollama is not running.
    """
    if not raw_text or raw_text.startswith("["):
        return ["NONE"]

    prompt = USER_PROMPT_TEMPLATE.replace("{text}", raw_text[:10000])

    if OLLAMA_AVAILABLE:
        try:
            # Same call pattern as selenium_nexus.ipynb call_llm()
            resp = _ollama.chat(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                format="json",
            )
            result_text = resp["message"]["content"]
            return _parse_llm_response(result_text)
        except Exception as e:
            print(f"    Ollama error: {e} — falling back to regex")
            return extract_regex(raw_text, ticker)
    else:
        print(f"    Ollama not available — falling back to regex")
        return extract_regex(raw_text, ticker)


# ============================================================
# OpenAI / Anthropic LLM Extraction (alternative providers)
# ============================================================

def extract_api_llm(raw_text, ticker, provider):
    """Use OpenAI or Anthropic API to extract subsidiaries."""
    if not raw_text or raw_text.startswith("["):
        return ["NONE"]

    prompt = USER_PROMPT_TEMPLATE.replace("{text}", raw_text[:10000])

    try:
        if provider == "openai":
            key = os.environ.get("OPENAI_API_KEY", "")
            if not key:
                print("    No OPENAI_API_KEY set, falling back to regex")
                return extract_regex(raw_text, ticker)

            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ], "temperature": 0, "max_tokens": 4000},
                timeout=60,
            )
            r.raise_for_status()
            return _parse_llm_response(r.json()["choices"][0]["message"]["content"])

        elif provider == "anthropic":
            key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not key:
                print("    No ANTHROPIC_API_KEY set, falling back to regex")
                return extract_regex(raw_text, ticker)

            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "Content-Type": "application/json"},
                json={"model": "claude-sonnet-4-20250514", "max_tokens": 4000,
                      "system": SYSTEM_PROMPT,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=60,
            )
            r.raise_for_status()
            return _parse_llm_response(r.json()["content"][0]["text"])

    except Exception as e:
        print(f"    {provider} error: {e}, falling back to regex")
        return extract_regex(raw_text, ticker)


def _parse_llm_response(text):
    """Parse LLM response to extract JSON array of subsidiary names."""
    text = text.strip()
    # Handle responses wrapped in {"subsidiaries": [...]} format
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            # Ollama json format might wrap in an object
            for key in ["subsidiaries", "names", "results", "data"]:
                if key in parsed and isinstance(parsed[key], list):
                    result = [str(x) for x in parsed[key] if x]
                    return result if result else ["NONE"]
        if isinstance(parsed, list):
            result = [str(x) for x in parsed if x]
            return result if result else ["NONE"]
    except json.JSONDecodeError:
        pass

    # Try to find JSON array in the response
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list) and all(isinstance(x, str) for x in result):
                return result if result else ["NONE"]
        except json.JSONDecodeError:
            pass
    return ["NONE"]


# ============================================================
# Regex Extraction (fallback if no LLM available)
# ============================================================

def clean_name(name):
    """Remove legal suffixes from company name (Step 2 requirement)."""
    suffixes = [
        r",?\s*LLC$", r",?\s*Inc\.?$", r",?\s*Ltd\.?$", r",?\s*Corp\.?$",
        r",?\s*L\.?P\.?$", r",?\s*S\.?A\.?$", r",?\s*GmbH$", r",?\s*B\.?V\.?$",
        r",?\s*Pte\.?$", r",?\s*Limited$", r",?\s*N\.?A\.?$", r",?\s*plc$",
        r",?\s*S\.?r\.?l\.?$", r",?\s*AG$", r",?\s*ULC$", r",?\s*SE$",
        r",?\s*Pty$", r",?\s*Unlimited Company$", r",?\s*Company$",
        r",?\s*Corporation$", r",?\s*Incorporated$",
    ]
    cleaned = name.strip()
    for suffix in suffixes:
        cleaned = re.sub(suffix, "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.rstrip(",. ")
    return cleaned


def extract_regex(raw_text, ticker):
    """
    Fallback: Extract subsidiary names from Exhibit 21.1 using regex/heuristics.
    Used when Ollama is not available.
    """
    if not raw_text or raw_text.startswith("["):
        return ["NONE"]

    lines = raw_text.split("\n")
    subsidiaries = []

    skip_patterns = [
        r"^exhibit", r"^subsidiaries?\s+(of|list)", r"^list\s+of",
        r"^the\s+following", r"^name\s+of", r"^jurisdiction",
        r"^state\s+or", r"^country", r"^where\s+inc",
        r"^pursuant", r"^\*", r"^as\s+of\s+\w+\s+\d",
        r"^100\s*%", r"^percent", r"^legal\s+name",
        r"^\d{1,2}/\d{1,2}/\d{2,4}", r"^page\s+\d",
        r"^form\s+10", r"^annual\s+report", r"^item\s+\d",
        r"^note:", r"^registrant",
    ]

    jurisdictions = {
        "delaware", "california", "new york", "texas", "nevada", "florida",
        "illinois", "ohio", "pennsylvania", "georgia", "virginia", "maryland",
        "massachusetts", "washington", "new jersey", "colorado", "arizona",
        "minnesota", "wisconsin", "missouri", "tennessee", "connecticut",
        "oregon", "iowa", "utah", "north carolina", "michigan", "indiana",
        "nebraska", "hawaii", "kentucky", "louisiana", "oklahoma", "kansas",
        "alabama", "south carolina", "rhode island", "maine", "vermont",
        "united states", "united kingdom", "ireland", "cayman islands",
        "bermuda", "luxembourg", "netherlands", "singapore", "canada",
        "hong kong", "japan", "germany", "france", "australia", "switzerland",
        "brazil", "india", "china", "korea", "south korea", "israel",
        "sweden", "denmark", "italy", "spain", "mexico", "belgium",
        "england and wales", "northern ireland", "scotland", "puerto rico",
        "virgin islands", "mauritius", "thailand", "russia", "u.s.",
    }

    for line in lines:
        line = line.strip()
        if not line or len(line) < 3 or len(line) > 300:
            continue

        lower = line.lower()

        if any(re.match(p, lower) for p in skip_patterns):
            continue
        if lower in jurisdictions:
            continue
        if re.match(r'^[\d\s.,%/$()-]+$', line):
            continue

        parts = re.split(r'\t+|\s{3,}', line)
        name = parts[0].strip()

        if name.lower() in jurisdictions:
            continue
        if len(name) < 3:
            continue
        if not name[0].isupper() and not name[0].isdigit():
            continue
        if name.upper() == ticker:
            continue

        cleaned = clean_name(name)
        if len(cleaned) >= 2:
            subsidiaries.append(cleaned)

    seen = set()
    unique = []
    for s in subsidiaries:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return unique if unique else ["NONE"]


# ============================================================
# Step 3: Format to JSON Schema + Step 4: Execute Pipeline
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extract subsidiaries from raw Exhibit 21.1 text"
    )
    parser.add_argument(
        "--llm",
        choices=["ollama", "openai", "anthropic", "regex"],
        default="ollama",
        help="LLM provider (default: ollama, matching the existing notebook)"
    )
    args = parser.parse_args()

    # Load .env if it exists (same as notebook's load_dotenv())
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

    tickers = load_tickers()
    results = []

    method_label = args.llm
    if args.llm == "ollama":
        method_label = f"ollama ({LLM_MODEL})" + (" [available]" if OLLAMA_AVAILABLE else " [not available — will fallback to regex]")

    print(f"Extracting subsidiaries for {len(tickers)} tickers")
    print(f"  Method: {method_label}")
    print()

    for i, ticker in enumerate(tickers):
        raw_file = RAW_DIR / f"{ticker}.txt"

        if not raw_file.exists():
            print(f"  [{i+1}/{len(tickers)}] {ticker}: no raw file")
            results.append({"ticker": ticker, "subsidiaries": ["NONE"]})
            continue

        raw_text = raw_file.read_text(encoding="utf-8", errors="replace")

        # Extract using selected method
        if args.llm == "ollama":
            subs = extract_ollama(raw_text, ticker)
        elif args.llm in ("openai", "anthropic"):
            subs = extract_api_llm(raw_text, ticker, args.llm)
        else:
            subs = extract_regex(raw_text, ticker)

        # Format to target JSON schema (Step 3)
        entry = {"ticker": ticker, "subsidiaries": subs}
        results.append(entry)

        count = len(subs) if subs != ["NONE"] else 0
        print(f"  [{i+1}/{len(tickers)}] {ticker}: {count} subsidiaries")

    # Write master subsidiaries.json
    OUTPUT.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    # Summary
    has_subs = sum(1 for r in results if r["subsidiaries"] != ["NONE"])
    total_subs = sum(len(r["subsidiaries"]) for r in results if r["subsidiaries"] != ["NONE"])
    print(f"\nDone!")
    print(f"  Tickers processed: {len(results)}")
    print(f"  With subsidiaries: {has_subs}")
    print(f"  Total subsidiaries: {total_subs}")
    print(f"  Output: {OUTPUT}")


if __name__ == "__main__":
    main()