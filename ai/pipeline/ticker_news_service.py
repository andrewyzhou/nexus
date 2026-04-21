from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import aiohttp
from dotenv import load_dotenv

from ai.pipeline.model_registry import load_registry
from ai.pipeline.news_scraper import NewsScraper
from ai.pipeline.news_summarizer import NewsSummarizer


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _model_label(summarizer: NewsSummarizer) -> str | None:
    return summarizer.model_config.model if summarizer else None


def _build_news_items(
    articles: list[dict[str, Any]],
    *,
    ticker_override: str | None = None,
    limit: int | None = None,
    include_text: bool = False,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for article in articles:
        item = {
            "title": article.get("title", ""),
            "link": article.get("url", ""),
            "publisher": article.get("source", "Unknown"),
            "published": article.get("published"),
            "summary": article.get("summary", ""),
            "ticker": ticker_override or article.get("ticker", ""),
        }
        if include_text:
            item["text"] = article.get("text", "")
        items.append(item)
    if limit is not None:
        return items[:limit]
    return items


def _citations_from_indices(
    articles: list[dict[str, Any]],
    citation_indices: list[int],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[int] = set()
    for idx in citation_indices:
        if idx in seen or idx < 0 or idx >= len(articles):
            continue
        seen.add(idx)
        article = articles[idx]
        citations.append(
            {
                "ref": len(citations) + 1,
                "article_index": idx,
                "cited_text": article.get("title") or article.get("summary") or "",
            }
        )
    return citations


async def _scrape_ticker_articles(
    scraper: NewsScraper,
    session: aiohttp.ClientSession,
    ticker: str,
    company_name: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        articles = await scraper.scrape_all_articles(session, ticker, company_name)
        return articles, None
    except Exception as e:
        return [], str(e)


async def get_ticker_news_summary(
    ticker: str,
    *,
    company_name: str | None = None,
    summarizer_model: str | None = None,
    scraper: NewsScraper | None = None,
    summarizer: NewsSummarizer | None = None,
    session: aiohttp.ClientSession | None = None,
    news_limit: int | None = None,
    include_summary: bool = True,
) -> dict[str, Any]:
    """Return backend/frontend-ready news and summary payload for a single ticker."""
    load_dotenv()

    normalized_ticker = (ticker or "").upper().strip()
    if not normalized_ticker:
        raise ValueError("ticker must be a non-empty symbol")

    local_scraper = scraper or NewsScraper()

    if summarizer is None:
        registry = load_registry()
        model_to_use = summarizer_model or "claude-sonnet"
        local_summarizer = NewsSummarizer(model_name=model_to_use, registry=registry)
    else:
        local_summarizer = summarizer

    owns_session = session is None
    active_session = session
    if active_session is None:
        connector = aiohttp.TCPConnector(limit=20)
        active_session = aiohttp.ClientSession(connector=connector)

    try:
        articles, scrape_error = await _scrape_ticker_articles(
            local_scraper,
            active_session,
            normalized_ticker,
            company_name,
        )
        visible_news = _build_news_items(
            articles,
            ticker_override=normalized_ticker,
            limit=news_limit,
        )
        summary_articles = _build_news_items(
            articles,
            ticker_override=normalized_ticker,
            limit=news_limit,
            include_text=True,
        )

        summary_error: str | None = None
        if not visible_news:
            summary_text = ""
            citation_indices: list[int] = []
            status = "scrape_error" if scrape_error else "no_news"
        elif not include_summary:
            summary_text = ""
            citation_indices = []
            status = "ok"
        else:
            try:
                summary_result = await local_summarizer.summarize_articles(
                    subject=normalized_ticker,
                    articles=summary_articles,
                    sentence_budget="3-5 sentences",
                )
                summary_text = summary_result.summary
                citation_indices = summary_result.citation_article_indices
                status = "ok"
            except Exception as e:
                summary_text = ""
                citation_indices = []
                summary_error = str(e)
                status = "summary_error"

        citations = _citations_from_indices(visible_news, citation_indices)
        return {
            "ticker": normalized_ticker,
            "news": visible_news,
            "summary": summary_text,
            "citations": citations,
            "used_articles": len(visible_news),
            "cached": False,
            "model": _model_label(local_summarizer) if include_summary else None,
            "as_of": _iso_now(),
            "status": status,
            "errors": {
                "scrape_error": scrape_error,
                "summary_error": summary_error,
            },
        }
    finally:
        if owns_session and active_session is not None:
            await active_session.close()


async def get_track_news_payload(
    constituents: list[dict[str, str]],
    *,
    track_name: str,
    summarizer_model: str | None = None,
    scraper: NewsScraper | None = None,
    summarizer: NewsSummarizer | None = None,
    session: aiohttp.ClientSession | None = None,
    per_company: int = 3,
    include_summary: bool = True,
) -> dict[str, Any]:
    """Return frontend-ready aggregated news and summary payload for a track."""
    load_dotenv()

    local_scraper = scraper or NewsScraper()
    if summarizer is None:
        registry = load_registry()
        model_to_use = summarizer_model or "claude-sonnet"
        local_summarizer = NewsSummarizer(model_name=model_to_use, registry=registry)
    else:
        local_summarizer = summarizer

    owns_session = session is None
    active_session = session
    if active_session is None:
        connector = aiohttp.TCPConnector(limit=20)
        active_session = aiohttp.ClientSession(connector=connector)

    try:
        aggregated_articles: list[dict[str, Any]] = []
        scrape_errors: dict[str, str] = {}
        for constituent in constituents:
            ticker = (constituent.get("ticker") or "").upper().strip()
            if not ticker:
                continue
            articles, scrape_error = await _scrape_ticker_articles(
                local_scraper,
                active_session,
                ticker,
                constituent.get("name"),
            )
            if scrape_error:
                scrape_errors[ticker] = scrape_error
            aggregated_articles.extend(articles[: max(0, per_company)])

        news_items = _build_news_items(aggregated_articles)
        summary_articles = _build_news_items(aggregated_articles, include_text=True)
        summary_error: str | None = None
        if not news_items:
            summary_text = ""
            citation_indices = []
            status = "scrape_error" if scrape_errors else "no_news"
        elif not include_summary:
            summary_text = ""
            citation_indices = []
            status = "ok"
        else:
            try:
                summary_result = await local_summarizer.summarize_articles(
                    subject=f"the {track_name} investment track",
                    articles=summary_articles,
                    sentence_budget="3-5 sentences or a short bulleted list when useful",
                )
                summary_text = summary_result.summary
                citation_indices = summary_result.citation_article_indices
                status = "ok"
            except Exception as e:
                summary_text = ""
                citation_indices = []
                summary_error = str(e)
                status = "summary_error"

        return {
            "news": news_items,
            "summary": summary_text,
            "citations": _citations_from_indices(news_items, citation_indices),
            "used_articles": len(news_items),
            "cached": False,
            "model": _model_label(local_summarizer) if include_summary else None,
            "as_of": _iso_now(),
            "status": status,
            "errors": {
                "scrape_error": None if not scrape_errors else "; ".join(
                    f"{ticker}: {err}" for ticker, err in sorted(scrape_errors.items())
                ),
                "summary_error": summary_error,
            },
        }
    finally:
        if owns_session and active_session is not None:
            await active_session.close()


def get_ticker_news_summary_sync(
    ticker: str,
    *,
    company_name: str | None = None,
    summarizer_model: str | None = None,
    news_limit: int | None = None,
    include_summary: bool = True,
) -> dict[str, Any]:
    return asyncio.run(
        get_ticker_news_summary(
            ticker,
            company_name=company_name,
            summarizer_model=summarizer_model,
            news_limit=news_limit,
            include_summary=include_summary,
        )
    )


def get_track_news_payload_sync(
    constituents: list[dict[str, str]],
    *,
    track_name: str,
    summarizer_model: str | None = None,
    per_company: int = 3,
    include_summary: bool = True,
) -> dict[str, Any]:
    return asyncio.run(
        get_track_news_payload(
            constituents,
            track_name=track_name,
            summarizer_model=summarizer_model,
            per_company=per_company,
            include_summary=include_summary,
        )
    )
