"""
Step 1: Scraper — Pulls Exhibit 21.1 (subsidiaries) from SEC EDGAR.
Saves raw text to raw_exhibits/<TICKER>.txt

Built on top of the existing selenium_nexus.ipynb EDGAR scraping logic:
  - Reuses CIK_MAP pattern and EDGAR_HEADERS from Cell 2a / 2f
  - Reuses fetch_edgar_json_api submissions endpoint pattern from Cell 2f
  - Reuses make_driver / Selenium setup from Cell 1
  - Redirects scraping target from 10-K business text → Exhibit 21.1

Usage:
    python scraper.py              # requests-only mode (faster, default)
    python scraper.py --selenium   # use Selenium like the existing notebook
"""

import json
import time
import re
import os
import argparse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ─── Config (from selenium_nexus.ipynb Cell 2a/2f) ──────────────────────────

TICKERS_FILE = "tickers.txt"
RAW_DIR = Path("raw_exhibits")
CIK_CACHE = Path("cik_cache.json")

# Same User-Agent pattern as selenium_nexus.ipynb EDGAR_HEADERS
EDGAR_HEADERS = {"User-Agent": "NexusAI research@berkeley.edu"}

# SEC rate limit: 10 req/s (same as selenium_nexus.ipynb Cell 2f)
DELAY = 0.12

# CIK_MAP from selenium_nexus.ipynb Cell 2a — extended for our ticker list.
# For tickers not hardcoded here, we fall back to SEC's full ticker-CIK JSON.
CIK_MAP_HARDCODED = {
    "NVDA": "0001045810", "MSFT": "0000789019", "GOOGL": "0001652044",
    "AMZN": "0001018724", "META": "0001326801", "TSM":   "0001046385",
}


# ─── Ticker loading ─────────────────────────────────────────────────────────

def load_tickers():
    return [t.strip().upper() for t in Path(TICKERS_FILE).read_text().splitlines() if t.strip()]


# ─── CIK mapping (extends selenium_nexus.ipynb CIK_MAP) ─────────────────────

def get_cik_map():
    """
    Build full ticker -> CIK mapping. Starts with the hardcoded CIK_MAP from
    selenium_nexus.ipynb, then supplements with SEC's full company_tickers.json.
    """
    if CIK_CACHE.exists():
        return json.loads(CIK_CACHE.read_text())

    print("Downloading full CIK mapping from SEC (extends notebook CIK_MAP)...")
    time.sleep(DELAY)
    r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=EDGAR_HEADERS)
    r.raise_for_status()

    # Start with hardcoded map from the notebook
    mapping = dict(CIK_MAP_HARDCODED)

    # Add all tickers from SEC (won't overwrite hardcoded ones)
    for entry in r.json().values():
        ticker = entry["ticker"].upper()
        if ticker not in mapping:
            mapping[ticker] = str(entry["cik_str"]).zfill(10)

    CIK_CACHE.write_text(json.dumps(mapping, indent=2))
    print(f"  Cached {len(mapping)} ticker-CIK mappings")
    return mapping


# ─── EDGAR Submissions API (same pattern as selenium_nexus.ipynb Cell 2f) ────

def find_exhibit_21_url(cik):
    """
    Find Exhibit 21.1 URL from the most recent 10-K filing.

    Uses the same data.sec.gov/submissions/ endpoint as fetch_edgar_json_api
    in selenium_nexus.ipynb Cell 2f, but instead of returning filing metadata,
    we navigate into the filing index to locate the Exhibit 21.1 document.
    """
    cik_padded = cik.zfill(10)

    # Same API call pattern as selenium_nexus.ipynb fetch_edgar_json_api
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    time.sleep(DELAY)
    r = requests.get(url, headers=EDGAR_HEADERS)
    if r.status_code != 200:
        return None

    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])

    # Find most recent 10-K (same logic as notebook's form_type loop)
    tenk_acc = None
    for i, form in enumerate(forms):
        if form in ("10-K", "10-K/A", "20-F", "20-F/A"):
            tenk_acc = accessions[i]
            break

    if not tenk_acc:
        return None

    acc_clean = tenk_acc.replace("-", "")
    cik_num = cik.lstrip("0") or cik

    # Get filing index page and hunt for Exhibit 21.1
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_clean}/{tenk_acc}-index.htm"
    time.sleep(DELAY)
    r = requests.get(index_url, headers=EDGAR_HEADERS)
    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Search links for ex21 patterns
    for link in soup.find_all("a", href=True):
        href = link["href"].lower()
        if any(x in href for x in ["ex21", "ex-21", "exhibit21", "exhibit-21"]):
            full = link["href"]
            if not full.startswith("http"):
                full = "https://www.sec.gov" + full
            return full

    # Also check table rows for "EX-21" or "subsidiaries" in description
    for row in soup.find_all("tr"):
        text = row.get_text().lower()
        if "ex-21" in text or "exhibit 21" in text or "subsidiaries" in text:
            for link in row.find_all("a", href=True):
                full = link["href"]
                if not full.startswith("http"):
                    full = "https://www.sec.gov" + full
                return full

    return None


# ─── Exhibit 21.1 text extraction ────────────────────────────────────────────

def scrape_exhibit_requests(url):
    """Download Exhibit 21.1 and extract text using requests + BeautifulSoup."""
    time.sleep(DELAY)
    r = requests.get(url, headers=EDGAR_HEADERS)
    if r.status_code != 200:
        return None

    if url.lower().endswith(".pdf"):
        return "[PDF - NEEDS MANUAL REVIEW]"

    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    text = soup.get_text(separator=" \n ")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines)[:100000]


def scrape_exhibit_selenium(url, driver):
    """
    Download Exhibit 21.1 using Selenium (same pattern as selenium_nexus.ipynb
    Cell 2a: scrape_sec_edgar_10k). Uses driver.get + BeautifulSoup on page_source,
    plus JS scroll for lazy-loading pages.
    """
    try:
        driver.get(url)
        time.sleep(1.5)

        # JS scroll to load lazy content (from notebook Cell 2a)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 3);")
        time.sleep(0.8)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return "\n".join(lines)[:15000]
    except Exception as e:
        print(f"    Selenium scrape failed: {e}")
        return None


# ─── Selenium driver setup (from selenium_nexus.ipynb Cell 1) ────────────────

def make_driver():
    """
    Same driver setup as selenium_nexus.ipynb make_driver().
    Only imported if --selenium flag is used.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
    except ImportError:
        print("  webdriver-manager not installed, using default chromedriver")
        service = Service()

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    opts.add_argument(f"--user-agent={ua}")

    driver = webdriver.Chrome(service=service, options=opts)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


# ─── Main pipeline ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Scrape Exhibit 21.1 from SEC EDGAR")
    parser.add_argument("--selenium", action="store_true",
                        help="Use Selenium (like notebook) instead of requests")
    args = parser.parse_args()

    RAW_DIR.mkdir(exist_ok=True)
    tickers = load_tickers()
    cik_map = get_cik_map()

    driver = None
    if args.selenium:
        print("Starting Chrome driver (from selenium_nexus.ipynb make_driver)...")
        driver = make_driver()
        print("  Chrome ready")

    mode = "selenium" if args.selenium else "requests"
    print(f"\nScraping Exhibit 21.1 for {len(tickers)} tickers (mode: {mode})...\n")

    stats = {"ok": 0, "cached": 0, "missing": 0, "no_cik": 0}

    for i, ticker in enumerate(tickers):
        outfile = RAW_DIR / f"{ticker}.txt"

        # Skip if already scraped
        if outfile.exists() and outfile.stat().st_size > 10:
            stats["cached"] += 1
            print(f"  [{i+1}/{len(tickers)}] {ticker}: cached")
            continue

        # Get CIK (check hardcoded map first, then full map)
        cik = cik_map.get(ticker) or cik_map.get(ticker.replace(".", "-"))
        if not cik:
            print(f"  [{i+1}/{len(tickers)}] {ticker}: no CIK found")
            outfile.write_text("[NO_CIK]")
            stats["no_cik"] += 1
            continue

        # Find Exhibit 21.1 URL
        ex_url = find_exhibit_21_url(cik)
        if not ex_url:
            print(f"  [{i+1}/{len(tickers)}] {ticker}: no Exhibit 21 found")
            outfile.write_text("[NO_EXHIBIT]")
            stats["missing"] += 1
            continue

        # Scrape the exhibit text
        if args.selenium and driver:
            text = scrape_exhibit_selenium(ex_url, driver)
        else:
            text = scrape_exhibit_requests(ex_url)

        if text and not text.startswith("["):
            outfile.write_text(text, encoding="utf-8")
            stats["ok"] += 1
            print(f"  [{i+1}/{len(tickers)}] {ticker}: OK ({len(text)} chars)")
        else:
            outfile.write_text(text or "[SCRAPE_FAILED]")
            stats["missing"] += 1
            print(f"  [{i+1}/{len(tickers)}] {ticker}: failed")

    if driver:
        driver.quit()

    print(f"\nDone! Scraped: {stats['ok']}, Cached: {stats['cached']}, "
          f"Missing: {stats['missing']}, No CIK: {stats['no_cik']}")


if __name__ == "__main__":
    main()
