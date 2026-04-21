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


class SummaryWithCitations(BaseModel):
    summary: str = Field(
        description=(
            "A concise markdown-safe news brief. Use short bullets only when the news clearly breaks into distinct items."
        )
    )
    citation_article_indices: list[int] = Field(
        description=(
            "Zero-based article indices backing the summary, ordered by importance. "
            "Only include indices that exist in the provided article list."
        )
    )


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

    def _clip_text(self, value: object, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    def summarize_articles_prompt(
        self,
        *,
        subject: str,
        articles: list[dict[str, object]],
        sentence_budget: str,
    ) -> str:
        intro = (
            f"You are writing a factual investor-facing news brief about {subject}. "
            f"Write {sentence_budget}. Be specific about dates and numbers when the article text includes them. "
            "Do not invent facts and do not give investment advice. "
            "Return only JSON matching the schema. "
            "Include the zero-based article indices that support the summary in citation_article_indices.\n\n"
            "Articles:\n"
        )
        article_blocks = []
        total_len = len(intro)
        for idx, article in enumerate(articles):
            block = "\n".join(
                [
                    f"Article {idx}:",
                    f"Title: {self._clip_text(article.get('title', ''), 180)}",
                    f"Publisher: {self._clip_text(article.get('publisher') or article.get('source') or '', 80)}",
                    f"Published: {self._clip_text(article.get('published', ''), 40)}",
                    f"URL: {self._clip_text(article.get('link') or article.get('url') or '', 220)}",
                    f"Summary: {self._clip_text(article.get('summary', ''), 500)}",
                    f"Text: {self._clip_text(article.get('text') or article.get('full_text') or '', 1200)}",
                ]
            )
            projected = total_len + len(block) + 2
            if article_blocks and projected > self.max_prompt_chars:
                break
            if not article_blocks and projected > self.max_prompt_chars:
                block = "\n".join(
                    [
                        f"Article {idx}:",
                        f"Title: {self._clip_text(article.get('title', ''), 120)}",
                        f"Publisher: {self._clip_text(article.get('publisher') or article.get('source') or '', 60)}",
                        f"Published: {self._clip_text(article.get('published', ''), 40)}",
                        f"URL: {self._clip_text(article.get('link') or article.get('url') or '', 180)}",
                        f"Summary: {self._clip_text(article.get('summary', ''), 300)}",
                        f"Text: {self._clip_text(article.get('text') or article.get('full_text') or '', 500)}",
                    ]
                )
            article_blocks.append(block)
            total_len += len(block) + 2

        context = "\n\n".join(article_blocks)
        return intro + context

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

    async def summarize_articles(
        self,
        *,
        subject: str,
        articles: list[dict[str, object]],
        sentence_budget: str = "3-5 sentences",
    ) -> SummaryWithCitations:
        if not articles:
            return SummaryWithCitations(summary="", citation_article_indices=[])

        if not self.client:
            count = min(3, len(articles))
            return SummaryWithCitations(
                summary="Mock summary sentence 1. Mock summary sentence 2.",
                citation_article_indices=list(range(count)),
            )

        prompt = self.summarize_articles_prompt(
            subject=subject,
            articles=articles,
            sentence_budget=sentence_budget,
        )
        parsed = await self.client.create_structured(prompt, SummaryWithCitations)
        valid_indices = [
            idx
            for idx in parsed.citation_article_indices
            if isinstance(idx, int) and 0 <= idx < len(articles)
        ]
        deduped_indices: list[int] = []
        for idx in valid_indices:
            if idx not in deduped_indices:
                deduped_indices.append(idx)
        return SummaryWithCitations(
            summary=parsed.summary.strip(),
            citation_article_indices=deduped_indices,
        )


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
