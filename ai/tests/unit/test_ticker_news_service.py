import asyncio
from unittest.mock import AsyncMock, patch

from ai.pipeline.news_summarizer import SummaryWithCitations
from ai.pipeline.ticker_news_service import (
    get_ticker_news_summary,
    get_track_news_payload,
)


def _article(
    *,
    ticker: str,
    title: str,
    url: str,
    source: str = "Reuters",
    published: str = "2026-04-20T00:00:00Z",
    summary: str = "Short source summary.",
    text: str = "Full article text " + ("word " * 120),
    score: float = 1.0,
):
    return {
        "ticker": ticker,
        "title": title,
        "source": source,
        "url": url,
        "published": published,
        "summary": summary,
        "text": text,
        "score": score,
    }


class StubScraper:
    def __init__(self, mapping):
        self.mapping = mapping

    async def scrape_all_articles(self, session, ticker, company_name=None):
        return list(self.mapping.get(ticker, []))


class StubSummarizer:
    def __init__(self, model="claude-sonnet-4-20250514", response=None):
        self.model_config = type("Config", (), {"model": model, "name": "claude-sonnet"})
        self._response = response or SummaryWithCitations(
            summary="A concise summary.",
            citation_article_indices=[1, 0],
        )

    async def summarize_articles(self, **kwargs):
        return self._response


class TestTickerNewsService:
    def test_ticker_payload_matches_frontend_contract(self):
        scraper = StubScraper(
            {
                "NVDA": [
                    _article(ticker="NVDA", title="Nvidia launches chip", url="https://example.com/1"),
                    _article(ticker="NVDA", title="Nvidia signs deal", url="https://example.com/2"),
                ]
            }
        )
        summarizer = StubSummarizer(
            response=SummaryWithCitations(
                summary="Nvidia launched a new chip and signed a supply deal.",
                citation_article_indices=[0, 1],
            )
        )

        result = asyncio.run(
            get_ticker_news_summary("NVDA", scraper=scraper, summarizer=summarizer)
        )

        assert result["ticker"] == "NVDA"
        assert result["model"] == "claude-sonnet-4-20250514"
        assert result["used_articles"] == 2
        assert result["status"] == "ok"
        assert len(result["news"]) == 2
        assert result["news"][0]["publisher"] == "Reuters"
        assert result["news"][0]["published"] == "2026-04-20T00:00:00Z"
        assert result["news"][0]["summary"] == "Short source summary."
        assert result["citations"] == [
            {"ref": 1, "article_index": 0, "cited_text": "Nvidia launches chip"},
            {"ref": 2, "article_index": 1, "cited_text": "Nvidia signs deal"},
        ]

    def test_no_news_payload_stays_shape_stable(self):
        scraper = StubScraper({"NVDA": []})
        summarizer = StubSummarizer()

        result = asyncio.run(
            get_ticker_news_summary("NVDA", scraper=scraper, summarizer=summarizer)
        )

        assert result["news"] == []
        assert result["summary"] == ""
        assert result["citations"] == []
        assert result["used_articles"] == 0
        assert result["status"] == "no_news"

    def test_track_payload_aggregates_articles_and_citations(self):
        scraper = StubScraper(
            {
                "AAPL": [
                    _article(ticker="AAPL", title="Apple unveils hardware", url="https://example.com/apple"),
                    _article(ticker="AAPL", title="Apple supplier update", url="https://example.com/apple2"),
                ],
                "MSFT": [
                    _article(ticker="MSFT", title="Microsoft closes AI deal", url="https://example.com/msft"),
                ],
            }
        )
        summarizer = StubSummarizer(
            response=SummaryWithCitations(
                summary="- **AAPL** launch.\n- **MSFT** acquisition.",
                citation_article_indices=[2, 0],
            )
        )

        result = asyncio.run(
            get_track_news_payload(
                [
                    {"ticker": "AAPL", "name": "Apple"},
                    {"ticker": "MSFT", "name": "Microsoft"},
                ],
                track_name="Big Tech",
                scraper=scraper,
                summarizer=summarizer,
                per_company=2,
            )
        )

        assert result["used_articles"] == 3
        assert [item["ticker"] for item in result["news"]] == ["AAPL", "AAPL", "MSFT"]
        assert result["citations"] == [
            {"ref": 1, "article_index": 2, "cited_text": "Microsoft closes AI deal"},
            {"ref": 2, "article_index": 0, "cited_text": "Apple unveils hardware"},
        ]
