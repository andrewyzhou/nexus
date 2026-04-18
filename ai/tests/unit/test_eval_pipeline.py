import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from ai.pipeline.model_registry import load_registry
from ai.pipeline.summary_eval import OpenAICompatibleDeepEvalModel
from deepeval import assert_test
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
from deepeval.test_case import LLMTestCase


load_dotenv(Path(__file__).resolve().parents[2] / "pipeline" / ".env")
REGISTRY = load_registry(Path(__file__).resolve().parents[2] / "config" / "models.yaml")
HAS_API_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))


@pytest.mark.slow
@pytest.mark.skipif(not HAS_API_KEY, reason="ANTHROPIC_API_KEY not set")
def test_tooltip_summarization_accuracy():
    retrieved_context = (
        "Apple Inc. today announced a major breakthrough in semiconductor design, unveiling the M4 chip. "
        "The new chip increases processing speeds by 20% and reduces power consumption. "
        "Tim Cook stated this will be integrated into the new iPad Pro models launching next month. "
        "Shares for Apple ticked up 2% in pre-market trading."
    )

    generated_tooltip = (
        "Apple announced the new M4 semiconductor chip, which boosts processing speed by 20% and lowers power use. "
        "The chip will debut in next month's iPad Pro lineup."
    )

    test_case = LLMTestCase(
        input="Summarize the most important recent news about Apple Inc. in exactly two sentences.",
        actual_output=generated_tooltip,
        retrieval_context=[retrieved_context],
    )

    judge = OpenAICompatibleDeepEvalModel(REGISTRY.get("judges", "claude-sonnet"))
    faithfulness_metric = FaithfulnessMetric(threshold=0.8, model=judge)
    answer_relevancy_metric = AnswerRelevancyMetric(threshold=0.8, model=judge)

    assert_test(test_case, [faithfulness_metric, answer_relevancy_metric])
