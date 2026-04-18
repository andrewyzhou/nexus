from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepeval.metrics import (
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    GEval,
    SummarizationMetric,
)
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

from ai.pipeline.model_registry import ModelConfig, ModelRegistry, load_registry
from ai.pipeline.news_summarizer import NewsSummarizer
from ai.pipeline.openai_compatible import OpenAICompatibleClient


@dataclass
class SummaryRecord:
    label: str
    track: str
    scraped_text: str
    summary: str | None = None
    summarizer_model: str | None = None


class OpenAICompatibleDeepEvalModel(DeepEvalBaseLLM):
    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config
        self.client = OpenAICompatibleClient(model_config)
        super().__init__(model=model_config.model)

    def load_model(self):
        return self.client

    def generate(self, prompt: str, schema=None):
        if schema is not None:
            return self.client.create_structured_sync(prompt, schema), 0.0
        return self.client.create_text_sync(prompt), 0.0

    async def a_generate(self, prompt: str, schema=None):
        if schema is not None:
            return await self.client.create_structured(prompt, schema), 0.0
        return await self.client.create_text(prompt), 0.0

    def get_model_name(self):
        return self.model_config.name


class SummaryEvalHarness:
    def __init__(self, registry: ModelRegistry | None = None, config_path: str | Path | None = None):
        self.registry = registry or load_registry(config_path)

    def build_judge(self, judge_name: str | None = None) -> OpenAICompatibleDeepEvalModel:
        config = self.registry.get("judges", judge_name) if judge_name else self.registry.default_for("judges")
        return OpenAICompatibleDeepEvalModel(config)

    def create_metrics(self, judge_name: str | None = None):
        judge = self.build_judge(judge_name)
        return [
            FaithfulnessMetric(threshold=0.8, model=judge),
            AnswerRelevancyMetric(threshold=0.8, model=judge),
            SummarizationMetric(threshold=0.7, model=judge),
            GEval(
                name="MaterialCoverage",
                criteria=(
                    "Determine whether the summary captures the material company-specific news event in the source text "
                    "without adding unsupported claims."
                ),
                evaluation_params=[
                    LLMTestCaseParams.INPUT,
                    LLMTestCaseParams.ACTUAL_OUTPUT,
                    LLMTestCaseParams.RETRIEVAL_CONTEXT,
                ],
                threshold=0.7,
                model=judge,
            ),
        ]

    def build_test_case(self, record: SummaryRecord) -> LLMTestCase:
        return LLMTestCase(
            input=f"Summarize the most important recent news about {record.label} in exactly two sentences.",
            actual_output=record.summary or "",
            retrieval_context=[record.scraped_text],
        )

    async def generate_summaries(self, records: list[SummaryRecord], summarizer_name: str) -> list[SummaryRecord]:
        summarizer = NewsSummarizer(model_name=summarizer_name, registry=self.registry)
        track_news = {record.label: record.scraped_text for record in records}
        summaries = await summarizer.generate_batch_summaries(track_news)
        return [
            SummaryRecord(
                label=record.label,
                track=record.track,
                scraped_text=record.scraped_text,
                summary=summaries.get(record.label, ""),
                summarizer_model=summarizer_name,
            )
            for record in records
        ]

    def evaluate_records(self, records: list[SummaryRecord], judge_name: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for record in records:
            test_case = self.build_test_case(record)
            metric_results: dict[str, Any] = {}
            for metric in self.create_metrics(judge_name):
                metric.measure(test_case)
                metric_results[metric.__name__] = {
                    "score": metric.score,
                    "reason": getattr(metric, "reason", None),
                    "success": metric.is_successful(),
                }
            results.append(
                {
                    "label": record.label,
                    "track": record.track,
                    "summarizer_model": record.summarizer_model,
                    "judge_model": judge_name,
                    "summary": record.summary,
                    "metrics": metric_results,
                }
            )
        return results

    async def run_mode(
        self,
        records: list[SummaryRecord],
        mode: str = "smoke",
        summarizer_names: list[str] | None = None,
        judge_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if mode not in {"smoke", "matrix"}:
            raise ValueError("mode must be 'smoke' or 'matrix'")

        if mode == "smoke":
            summarizer_names = summarizer_names or [self.registry.default_for("summarizers").name]
            judge_names = judge_names or [self.registry.default_for("judges").name]
        else:
            summarizer_names = summarizer_names or self.registry.names("summarizers")
            judge_names = judge_names or self.registry.names("judges")

        all_results: list[dict[str, Any]] = []
        for summarizer_name in summarizer_names:
            generated_records = await self.generate_summaries(records, summarizer_name)
            for judge_name in judge_names:
                if not self.registry.get("judges", judge_name).available:
                    continue
                all_results.extend(self.evaluate_records(generated_records, judge_name))
        return all_results


def load_records(path: str | Path) -> list[SummaryRecord]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    records: list[SummaryRecord] = []
    for item in payload:
        scraped_text = item.get("scraped_text") or ""
        if not scraped_text.strip():
            continue
        records.append(
            SummaryRecord(
                label=item["label"],
                track=item.get("track", "unknown"),
                scraped_text=scraped_text,
                summary=item.get("summary"),
                summarizer_model=item.get("summarizer_model"),
            )
        )
    return records


def write_results(results: list[dict[str, Any]], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    csv_path = path.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "label",
                "track",
                "summarizer_model",
                "judge_model",
                "metric",
                "score",
                "success",
                "reason",
            ],
        )
        writer.writeheader()
        for row in results:
            for metric_name, metric_data in row["metrics"].items():
                writer.writerow(
                    {
                        "label": row["label"],
                        "track": row["track"],
                        "summarizer_model": row["summarizer_model"],
                        "judge_model": row["judge_model"],
                        "metric": metric_name,
                        "score": metric_data["score"],
                        "success": metric_data["success"],
                        "reason": metric_data["reason"],
                    }
                )
