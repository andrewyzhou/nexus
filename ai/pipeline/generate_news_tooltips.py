import argparse
import asyncio
import json
import os
from datetime import datetime, timezone

import aiohttp
import yaml
from dotenv import load_dotenv

from ai.pipeline.model_registry import load_registry
from ai.pipeline.news_scraper import NewsScraper
from ai.pipeline.news_summarizer import NewsSummarizer


def get_config_path() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "config", "tracks.yaml")


def load_tracks(test_mode: bool = False) -> dict[str, list[str]]:
    path = get_config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            key = "test_tracks" if test_mode else "investment_tracks"
            return config.get(key, {})
    except Exception as e:
        print(f"Error loading config from {path}: {e}")
        return {}


def get_output_path() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out_dir = os.path.join(base_dir, "scraper", "data", "processed")
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, "news_summaries.json")


async def scrape_track(
    session: aiohttp.ClientSession,
    track_name: str,
    tickers: list[str],
    scraper: NewsScraper,
):
    print(f"\n--- Scraping track: {track_name} ---")

    async def scrape_ticker(ticker: str):
        print(f"Scraping full text for {ticker}...")
        try:
            raw_text = await scraper.scrape_all(session, ticker)
            if raw_text and raw_text.strip():
                return ticker, raw_text
            print(f"No valid news text found for {ticker} across all sources.")
            return ticker, None
        except Exception as e:
            print(f"Error scraping {ticker}: {e}")
            return ticker, None

    raw_results = await asyncio.gather(*(scrape_ticker(t) for t in tickers))
    track_news_dict = {ticker: text for ticker, text in raw_results if text}
    return track_name, track_news_dict


async def async_main():
    parser = argparse.ArgumentParser(
        description="Generate UI tooltips for S&P 500 company news."
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Run with a small mock list of companies",
    )
    parser.add_argument(
        "--summarizer-model",
        help="Model registry entry to use for summarization",
    )
    args = parser.parse_args()

    load_dotenv()
    tracks = load_tracks(args.test_mode)
    registry = load_registry()

    if args.test_mode:
        print("Running in TEST MODE with tracks loaded from config...")

    scraper = NewsScraper()
    summarizer = NewsSummarizer(model_name=args.summarizer_model, registry=registry)

    all_results = []
    connector = aiohttp.TCPConnector(limit=50)
    async with aiohttp.ClientSession(connector=connector) as session:
        scraped_tracks = await asyncio.gather(
            *(scrape_track(session, track_name, tickers, scraper) for track_name, tickers in tracks.items())
        )

        for track_name, track_news_dict in scraped_tracks:
            if not track_news_dict:
                print(f"Skipping track '{track_name}': no underlying news was found.")
                continue

            print(
                f"Sending batch of {len(track_news_dict)} tickers to {summarizer.model_config.name} for track {track_name}..."
            )
            batch_summaries = await summarizer.generate_batch_summaries(track_news_dict)

            for ticker, summary in batch_summaries.items():
                all_results.append(
                    {
                        "label": ticker,
                        "track": track_name,
                        "accessed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "summary": summary,
                        "scraped_text": track_news_dict.get(ticker, ""),
                        "summarizer_model": summarizer.model_config.name,
                    }
                )

    out_path = get_output_path()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print(f"\nDone! Saved {len(all_results)} summaries to {out_path}")


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
