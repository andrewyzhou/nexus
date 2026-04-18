from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from dotenv import load_dotenv

from ai.pipeline.model_registry import load_registry
from ai.pipeline.news_summarizer import NewsSummarizer, TrackSummaries, TickerSummary


AI_DIR = Path(__file__).resolve().parents[1]
load_dotenv(AI_DIR / "pipeline" / ".env")


@pytest.fixture
def registry():
    return load_registry(AI_DIR / "config" / "models.yaml")


@pytest.fixture
def canned_track_news():
    return {
        "AAPL": (
            "Title: Apple Unveils M4 Chip\n"
            "Source: Reuters\n"
            "URL: https://example.com/apple\n"
            "Text: Apple Inc. today announced the M4 chip, offering a 20% speed increase "
            "and reduced power consumption. Tim Cook confirmed it will ship in the new iPad Pro."
        ),
        "MSFT": (
            "Title: Microsoft Closes AI Acquisition\n"
            "Source: Bloomberg\n"
            "URL: https://example.com/microsoft\n"
            "Text: Microsoft completed its acquisition of a major AI cloud infrastructure firm today. "
            "The deal is valued at $14 billion and is expected to accelerate Azure AI capabilities."
        ),
    }


@pytest.fixture
def mock_structured_summaries():
    return TrackSummaries(
        summaries=[
            TickerSummary(
                ticker="AAPL",
                summary="Apple launched the M4 chip with a 20% speed boost. It debuts in the new iPad Pro next month. [Source](https://example.com/apple)",
            ),
            TickerSummary(
                ticker="MSFT",
                summary="Microsoft closed a $14B AI infrastructure acquisition. The deal is expected to accelerate Azure AI. [Source](https://example.com/microsoft)",
            ),
        ]
    )


@pytest.fixture
def mock_openai_client(mock_structured_summaries):
    client = MagicMock()
    client.create_structured = AsyncMock(return_value=mock_structured_summaries)
    client.create_structured_sync.return_value = mock_structured_summaries
    client.create_text.return_value = "stub"
    client.create_text_sync.return_value = "stub"
    return client


@pytest.fixture
def mock_summarizer(registry, mock_openai_client):
    with patch("ai.pipeline.news_summarizer.OpenAICompatibleClient", return_value=mock_openai_client):
        summarizer = NewsSummarizer(model_name="local-qwen2.5-7b", registry=registry)
        yield summarizer
