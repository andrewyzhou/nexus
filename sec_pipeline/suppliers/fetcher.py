import time
import requests 
from bs4 import BeautifulSoup
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

full_name = os.getenv("FULL_NAME")
email = os.getenv("EMAIL")

HEADERS = {
    "User-Agent": f"{full_name} {email}",
    "Accept-Encoding": "gzip, deflate",
}

BASE = "https://data.sec.gov"

SECTION_TARGETS = {
    "supply_chain": {
        "start": ["supply chain", "supplier", "suppliers"],
        "end":   ["item 1a", "risk factors", "item 2", "vendors"],
    },
    "vendors": {
        "start": ["vendors", "vendor relationships", "vendor concentration"],
        "end":   ["item 1a", "risk factors", "item 2", "manufacturing"],
    },
    "manufacturing": {
        "start": ["manufacturing partners", "contract manufacturer", "outsourced manufacturing"],
        "end":   ["item 1a", "risk factors", "item 2", "raw materials"],
    },
    "raw_materials": {
        "start": ["raw materials", "components", "procurement"],
        "end":   ["item 1a", "risk factors", "item 2"],
    },
}


def get_cik(ticker: str) -> str:
    url = "https://www.sec.gov/files/company_tickers.json"
    r = requests.get(url, headers=HEADERS, timeout=15)
    data = r.json()
    for entry in data.values():
        if entry["ticker"].upper() == ticker.upper():
            return str(entry["cik_str"]).zfill(10)
    raise ValueError(f"Ticker {ticker} not found in SEC database")


def get_filings(cik: str, form_type: str = "10-K", count: int = 1) -> list:
    url = f"{BASE}/submissions/CIK{cik}.json"
    r = requests.get(url, headers=HEADERS, timeout=15)
    data = r.json()
    filings = data["filings"]["recent"]
    results = []
    for i, form in enumerate(filings["form"]):
        if form == form_type:
            results.append({
                "accessionNumber": filings["accessionNumber"][i],
                "filingDate":      filings["filingDate"][i],
                "primaryDocument": filings["primaryDocument"][i],
            })
            if len(results) >= count:
                break
    return results


def get_filing_text(cik: str, accession_number: str, doc_name: str) -> str:
    accession_clean = accession_number.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{doc_name}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    time.sleep(0.5)
    soup = BeautifulSoup(r.text, "lxml")
    return soup.get_text(separator=" ", strip=True)


def extract_section(text: str, start_keywords: list, end_keywords: list = None) -> str:
    text_lower = text.lower()
    start_idx = -1
    for keyword in start_keywords:
        idx = text_lower.find(keyword.lower())
        if idx != -1:
            start_idx = idx
            break
    if start_idx == -1:
        return ""
    end_idx = len(text)
    if end_keywords:
        for keyword in end_keywords:
            idx = text_lower.find(keyword.lower(), start_idx + 100)
            if idx != -1:
                end_idx = min(end_idx, idx)
    else:
        end_idx = start_idx + 5000
    return text[start_idx:end_idx].strip()


def fetch_sec_sections(ticker: str) -> dict:
    """
    For a given ticker, fetch the latest 10-K from SEC EDGAR
    and return isolated section texts for supply chain topics.
    Returns empty strings for sections not found.
    """
    try:
        cik = get_cik(ticker)
        filings = get_filings(cik, "10-K", count=1)

        if not filings:
            print(f"No 10-K found for {ticker}")
            return {name: "" for name in SECTION_TARGETS}

        filing = filings[0]
        print(f"Fetching 10-K for {ticker} ({filing['filingDate']})")

        raw_text = get_filing_text(cik, filing["accessionNumber"], filing["primaryDocument"])
        time.sleep(1)

        sections = {
            name: extract_section(
                raw_text,
                start_keywords=config["start"],
                end_keywords=config["end"]
            )
            for name, config in SECTION_TARGETS.items()
        }

        for name, text in sections.items():
            status = f"{len(text)} chars" if text else "not found"
            print(f"{name}: {status}")

        return sections

    except Exception as e:
        print(f"Error fetching SEC sections for {ticker}: {e}")
        return {name: "" for name in SECTION_TARGETS}


if __name__ == "__main__":
    tickers_file = Path("tickers.txt")
    output_dir = Path("raw_sections")
    output_dir.mkdir(parents=True, exist_ok=True)

    tickers = [
        line.strip().upper()
        for line in tickers_file.read_text().splitlines()
        if line.strip()
    ]

    for ticker in tickers:
        out_path = output_dir / f"{ticker}_sections.txt"
        if out_path.exists() and out_path.stat().st_size > 10:
            print(f"Skipping {ticker} (already cached)")
            continue
            
        print(f"\n{ticker}")
        sections = fetch_sec_sections(ticker)

        out_path = output_dir / f"{ticker}_sections.txt"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"TICKER: {ticker}\n")
            f.write("=" * 60 + "\n\n")
            for section_name, section_text in sections.items():
                f.write(f"--- {section_name.upper()} ---\n")
                f.write(section_text if section_text else "[NOT FOUND]")
                f.write("\n\n")

        print(f"Saved to {out_path}")

