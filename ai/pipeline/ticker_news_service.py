from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import aiohttp
from dotenv import load_dotenv

from ai.pipeline.model_registry import load_registry
from ai.pipeline.news_scraper import NewsScraper
from ai.pipeline.news_summarizer import NewsSummarizer


def _extract_sources(scraped_text: str) -> list[dict[str, str]]:
    """Extract structured source metadata from scraper output blocks."""
    if not scraped_text or not scraped_text.strip():
        return []

    blocks = [b.strip() for b in re.split(r"\n\n---\n\n", scraped_text) if b.strip()]
    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for block in blocks:
        title_match = re.search(r"^Title:\s*(.*)$", block, flags=re.MULTILINE)
        source_match = re.search(r"^Source:\s*(.*)$", block, flags=re.MULTILINE)
        url_match = re.search(r"^URL:\s*(.*)$", block, flags=re.MULTILINE)

        title = (title_match.group(1).strip() if title_match else "")
        source = (source_match.group(1).strip() if source_match else "Unknown")
        url = (url_match.group(1).strip() if url_match else "")

        if not title and not url:
            continue

        key = (title, url)
        if key in seen:
            continue
        seen.add(key)

        payload = {
            "title": title,
            "source": source,
            "url": url,
        }
        sources.append(payload)

    return sources


async def get_ticker_news_summary(
    ticker: str,
    *,
    company_name: str | None = None,
    summarizer_model: str | None = None,
    scraper: NewsScraper | None = None,
    summarizer: NewsSummarizer | None = None,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    """Return backend-friendly summary and sources for a single ticker."""
    load_dotenv()

    normalized_ticker = (ticker or "").upper().strip()
    if not normalized_ticker:
        raise ValueError("ticker must be a non-empty symbol")

    local_scraper = scraper or NewsScraper()

    if summarizer is None:
        registry = load_registry()
        local_summarizer = NewsSummarizer(model_name=summarizer_model, registry=registry)
    else:
        local_summarizer = summarizer

    owns_session = session is None
    active_session = session
    if active_session is None:
        connector = aiohttp.TCPConnector(limit=20)
        active_session = aiohttp.ClientSession(connector=connector)

    try:
        raw_text = await local_scraper.scrape_all(active_session, normalized_ticker, company_name)
        sources = _extract_sources(raw_text)

        if not raw_text or not raw_text.strip():
            summary_text = "No significant recent news."
            status = "no_news"
        else:
            summaries = await local_summarizer.generate_batch_summaries({normalized_ticker: raw_text})
            summary_text = summaries.get(normalized_ticker, "No significant recent news.")
            status = "ok" if "Error generating summary" not in summary_text else "summary_error"

        return {
            "ticker": normalized_ticker,
            "summary": summary_text,
            "sources": sources,
            "source_count": len(sources),
            "as_of": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": status,
            "summarizer_model": local_summarizer.model_config.name,
            "scraped_text": raw_text,
        }
    finally:
        if owns_session and active_session is not None:
            await active_session.close()


def get_ticker_news_summary_sync(
    ticker: str,
    *,
    company_name: str | None = None,
    summarizer_model: str | None = None,
) -> dict[str, Any]:
    """Synchronous wrapper around get_ticker_news_summary."""
    return asyncio.run(
        get_ticker_news_summary(
            ticker,
            company_name=company_name,
            summarizer_model=summarizer_model,
        )
    )
