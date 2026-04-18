import argparse
import asyncio
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and summarize recent ticker news with source links."
    )
    parser.add_argument("--ticker", required=True, help="Ticker symbol (for example: NVDA)")
    parser.add_argument("--company-name", default=None, help="Optional company name hint")
    parser.add_argument("--summarizer-model", default=None, help="Optional model registry key")
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()

    try:
        from ai.pipeline.ticker_news_service import get_ticker_news_summary
    except ModuleNotFoundError:
        # Allow direct script execution: python ai/pipeline/get_ticker_news.py ...
        repo_root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(repo_root))
        from ai.pipeline.ticker_news_service import get_ticker_news_summary

    result = await get_ticker_news_summary(
        args.ticker,
        company_name=args.company_name,
        summarizer_model=args.summarizer_model,
    )
    if args.pretty:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
