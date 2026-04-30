from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from ai.pipeline.model_registry import ModelRegistry, load_registry
from ai.pipeline.openai_compatible import OpenAICompatibleClient


class TickerSummary(BaseModel):
    ticker: str = Field(description="The stock ticker symbol")
    summary: str = Field(
        description=(
            "Exactly two sentences summarizing the breaking news for this company. "
            "Include the most relevant source URL at the end as [Source](URL)."
        )
    )


class TrackSummaries(BaseModel):
    summaries: list[TickerSummary]


class NewsSummarizer:
    def __init__(
        self,
        model_name: str | None = None,
        registry: ModelRegistry | None = None,
        config_path: str | Path | None = None,
        max_tickers_per_batch: int = 4,
        max_prompt_chars: int = 30000,
    ) -> None:
        self.registry = registry or load_registry(config_path)
        self.model_config = (
            self.registry.get("summarizers", model_name)
            if model_name
            else self.registry.default_for("summarizers")
        )
        self.client = (
            OpenAICompatibleClient(self.model_config)
            if self.model_config.available
            else None
        )
        self.max_tickers_per_batch = max_tickers_per_batch
        self.max_prompt_chars = max_prompt_chars

    def _build_prompt(self, track_news_dict: dict[str, str]) -> str:
        context_blocks = [
            f"--- TICKER: {ticker} ---\n{news_text}\n"
            for ticker, news_text in track_news_dict.items()
        ]
        full_context = "\n".join(context_blocks)
        return (
            "You are an expert financial analyst. Read the following full-text news articles for several companies. "
            "Each article includes a URL. Write exactly two sentences summarizing the breaking news for each company. "
            "If the provided context does not contain any concrete, recent company-specific news event, return exactly "
            "'No significant recent news.' for that ticker. Do not summarize general market definitions or broad sector commentary.\n\n"
            f"Context:\n{full_context}"
        )

    def _iter_chunks(self, track_news_dict: dict[str, str]) -> list[dict[str, str]]:
        chunks: list[dict[str, str]] = []
        current: dict[str, str] = {}

        for ticker, news_text in track_news_dict.items():
            candidate = dict(current)
            candidate[ticker] = news_text
            candidate_prompt = self._build_prompt(candidate)

            too_many_tickers = len(candidate) > self.max_tickers_per_batch
            too_many_chars = len(candidate_prompt) > self.max_prompt_chars

            if current and (too_many_tickers or too_many_chars):
                chunks.append(current)
                current = {ticker: news_text}
            else:
                current = candidate

        if current:
            chunks.append(current)

        return chunks

    async def _summarize_chunk(self, chunk: dict[str, str]) -> dict[str, str]:
        prompt = self._build_prompt(chunk)
        parsed_data = await self.client.create_structured(prompt, TrackSummaries)
        results: dict[str, str] = {}

        if parsed_data and parsed_data.summaries:
            for item in parsed_data.summaries:
                results[item.ticker] = item.summary.strip()

        for ticker in chunk:
            if ticker not in results:
                results[ticker] = "No significant recent news."

        return results

    async def generate_batch_summaries(
        self, track_news_dict: dict[str, str]
    ) -> dict[str, str]:
        if not self.client:
            print(
                f"Warning: no credentials available for summarizer '{self.model_config.name}'. Returning mock summaries."
            )
            return {
                ticker: "Mock summary sentence 1. Mock sentence 2."
                for ticker in track_news_dict
            }

        if not track_news_dict:
            return {}

        all_results: dict[str, str] = {}
        chunks = self._iter_chunks(track_news_dict)

        for i, chunk in enumerate(chunks, start=1):
            try:
                if len(chunks) > 1:
                    print(
                        f"Summarizing chunk {i}/{len(chunks)} with {self.model_config.name} ({len(chunk)} tickers)..."
                    )
                all_results.update(await self._summarize_chunk(chunk))
            except Exception as e:
                print(
                    f"Error generating batch summaries with {self.model_config.name}: {e}"
                )
                for ticker in chunk:
                    all_results[ticker] = "Error generating summary. Please check logs."

        return all_results


if __name__ == "__main__":
    summarizer = NewsSummarizer()
    mock_data = {
        "AAPL": (
            "Title: Apple announces amazing new tech.\n"
            "URL: https://example.com/apple\n"
            "Text: Apple Inc has officially unveiled its newest semiconductor today."
        )
    }
    print("Batch summaries JSON output:")
    print(asyncio.run(summarizer.generate_batch_summaries(mock_data)))
