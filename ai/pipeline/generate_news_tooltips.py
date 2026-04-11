import os
import json
import argparse
from datetime import datetime, timezone
from dotenv import load_dotenv
from ai.pipeline.news_scraper import NewsScraper
from ai.pipeline.news_summarizer import NewsSummarizer

def main():
    parser = argparse.ArgumentParser(description="Generate UI tooltips for S&P 500 company news.")
    parser.add_argument("--test-mode", action="store_true", help="Run with a small mock list of companies")
    args = parser.parse_args()
    
    load_dotenv()
    
    # Investing tracks 
    tracks = {
        "Big Tech AI Infrastructure": ["NVDA", "MSFT", "GOOGL", "AMZN", "META"],
        "Semiconductor Manufacturing & Equipment": ["ASML", "AMAT", "LRCX", "KLAC", "TSMC"],
        "Digital Payments & Fintech": ["V", "MA", "PYPL", "FI", "GPN"],
        "Cybersecurity SaaS": ["PANW", "FTNT", "CRWD", "OKTA", "ZS"]
    }
    
    if args.test_mode:
        tracks = {"Test Track": ["AAPL"]}
        print("Running in TEST MODE with AAPL...")
        
    scraper = NewsScraper(headless=True)
    summarizer = NewsSummarizer()
    
    results = []
    
    for track_name, tickers in tracks.items():
        print(f"\\n--- Processing track: {track_name} ---")
        for ticker in tickers:
            print(f"Scraping news for {ticker}...")
            try:
                raw_text = scraper.scrape_all(ticker)
                
                if not raw_text or len(raw_text.strip()) == 0:
                    print(f"No news text found for {ticker}.")
                    continue
                    
                keywords = summarizer.extract_keywords(raw_text, top_n=8)
                context = summarizer.extract_context(raw_text, keywords)
                
                print(f"Generating summary for {ticker}...")
                summary = summarizer.generate_summary(context, ticker)
                
                results.append({
                    "label": ticker,
                    "track": track_name,
                    "accessed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "summary": summary
                })
            except Exception as e:
                print(f"Error processing {ticker}: {e}")
                
    scraper.close()
    
    # Save output
    os.makedirs("scraper/data/processed", exist_ok=True)
    out_path = "scraper/data/processed/news_summaries.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\\nDone! Saved {len(results)} summaries to {out_path}")

if __name__ == "__main__":
    main()
