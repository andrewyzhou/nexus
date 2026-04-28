import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from ai.pipeline.news_scraper import NewsScraper
from ai.pipeline.news_summarizer import NewsSummarizer


class TestNewsSummarizer:
    def test_parses_valid_response(self, registry, mock_openai_client):
        with patch("ai.pipeline.news_summarizer.OpenAICompatibleClient", return_value=mock_openai_client):
            summarizer = NewsSummarizer(model_name="local-qwen2.5-7b", registry=registry)
            result = asyncio.run(summarizer.generate_batch_summaries({"AAPL": "Apple news text here."}))

        assert "AAPL" in result
        assert result["AAPL"].startswith("Apple launched the M4 chip")

    def test_no_credentials_returns_mock_summaries(self, registry):
        with patch.dict("os.environ", {}, clear=True):
            summarizer = NewsSummarizer(model_name="gemini-2.5-flash-lite", registry=registry)

        result = asyncio.run(summarizer.generate_batch_summaries({"MSFT": "Microsoft news."}))

        assert "MSFT" in result
        assert "Mock summary" in result["MSFT"]

    def test_empty_input_returns_empty_dict(self, registry, mock_openai_client):
        with patch("ai.pipeline.news_summarizer.OpenAICompatibleClient", return_value=mock_openai_client):
            summarizer = NewsSummarizer(model_name="local-qwen2.5-7b", registry=registry)
            result = asyncio.run(summarizer.generate_batch_summaries({}))

        assert result == {}
        mock_openai_client.create_structured.assert_not_called()

    def test_api_exception_returns_error_strings(self, registry, mock_openai_client):
        mock_openai_client.create_structured = AsyncMock(side_effect=Exception("API down"))

        with patch("ai.pipeline.news_summarizer.OpenAICompatibleClient", return_value=mock_openai_client):
            summarizer = NewsSummarizer(model_name="local-qwen2.5-7b", registry=registry)
            result = asyncio.run(
                summarizer.generate_batch_summaries({"NVDA": "Nvidia news.", "TSLA": "Tesla news."})
            )

        assert "NVDA" in result
        assert "TSLA" in result
        assert "Error generating summary" in result["NVDA"]
        assert "Error generating summary" in result["TSLA"]

    def test_batch_ticker_completeness(self, registry, mock_openai_client):
        partial = mock_openai_client.create_structured.return_value.model_copy()
        partial.summaries = partial.summaries[:1]
        mock_openai_client.create_structured = AsyncMock(return_value=partial)

        with patch("ai.pipeline.news_summarizer.OpenAICompatibleClient", return_value=mock_openai_client):
            summarizer = NewsSummarizer(model_name="local-qwen2.5-7b", registry=registry)
            result = asyncio.run(
                summarizer.generate_batch_summaries({"AAPL": "Apple news.", "MSFT": "Microsoft news."})
            )

        assert result["MSFT"] == "No significant recent news."

    def test_chunking_splits_large_input(self, registry, mock_openai_client):
        with patch("ai.pipeline.news_summarizer.OpenAICompatibleClient", return_value=mock_openai_client):
            summarizer = NewsSummarizer(
                model_name="local-qwen2.5-7b",
                registry=registry,
                max_tickers_per_batch=1,
            )
            result = asyncio.run(
                summarizer.generate_batch_summaries({"AAPL": "Apple news.", "MSFT": "Microsoft news."})
            )

        assert "AAPL" in result
        assert "MSFT" in result
        assert mock_openai_client.create_structured.await_count == 2


class TestNewsScraper:
    def test_mentions_ticker_or_company_allows_short_article(self):
        scraper = NewsScraper(finnhub_api_key="key")

        assert scraper._mentions_ticker_or_company(
            ticker="TM",
            title="TM shares rise after guidance update",
            summary="Short note",
            text="",
            company_name="Toyota Motor Corporation",
        )

        assert scraper._mentions_ticker_or_company(
            ticker="TM",
            title="Toyota updates EV plans",
            summary="Short note",
            text="",
            company_name="Toyota Motor Corporation",
        )

        assert not scraper._mentions_ticker_or_company(
            ticker="TM",
            title="Ford updates EV plans",
            summary="Short note",
            text="",
            company_name="Toyota Motor Corporation",
        )

    @pytest.mark.asyncio
    async def test_scrape_all_dedupes_urls(self):
        scraper = NewsScraper(finnhub_api_key="key")
        article_one = "Title: One\nSource: Finnhub API\nURL: https://example.com/a?utm_source=x\nText: body one " + ("word " * 120)
        article_two = "Title: Two\nSource: Reuters\nURL: https://example.com/a\nText: body two " + ("word " * 120)
        article_three = "Title: Three\nSource: Google News\nURL: https://example.com/b\nText: body three " + ("word " * 120)

        with (
            patch.object(scraper, "fetch_finnhub_tier", new=AsyncMock(return_value=[article_one])),
            patch.object(scraper, "fetch_yfinance_tier", new=AsyncMock(return_value=[article_two])),
            patch.object(scraper, "fetch_rss_tier", new=AsyncMock(return_value=[article_three])),
        ):
            result = await scraper.scrape_all(session=object(), ticker="AAPL", company_name="Apple")

        assert result.count("URL:") == 2
        assert "https://example.com/a?utm_source=x\n" in result
        assert "https://example.com/b\n" in result

    @pytest.mark.asyncio
    async def test_fetch_finnhub_tier_accepts_short_summary_when_ticker_matches(self):
        scraper = NewsScraper(finnhub_api_key="key")

        class FakeResponse:
            status = 200

            async def json(self):
                return [{
                    "url": "https://example.com/tm",
                    "headline": "TM rises on hybrid demand",
                    "summary": "TM said demand remained strong.",
                    "datetime": 1_713_657_600,
                }]

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeSession:
            def get(self, *args, **kwargs):
                return FakeResponse()

        with patch.object(scraper, "fetch_full_text", new=AsyncMock(return_value="")):
            result = await scraper.fetch_finnhub_tier(
                FakeSession(),
                "TM",
                "Toyota Motor Corporation",
            )

        assert len(result) == 1
        assert result[0]["title"] == "TM rises on hybrid demand"
        assert result[0]["summary"] == "TM said demand remained strong."
