import asyncio
from unittest.mock import patch

from ai.pipeline.summary_eval import SummaryEvalHarness, SummaryRecord, load_records


def test_registry_defaults(registry):
    assert registry.default_for("summarizers").name == "local-qwen2.5-7b"
    assert registry.default_for("judges").name == "claude-sonnet"
    assert "local-qwen2.5-7b" in registry.names("summarizers")


def test_load_records_filters_missing_scraped_text(tmp_path):
    path = tmp_path / "records.json"
    path.write_text(
        '[{"label":"AAPL","track":"tech","scraped_text":"body","summary":"ok"},'
        '{"label":"MSFT","track":"tech","scraped_text":""}]',
        encoding="utf-8",
    )

    records = load_records(path)
    assert len(records) == 1
    assert records[0].label == "AAPL"


def test_smoke_mode_uses_default_models(registry):
    harness = SummaryEvalHarness(registry=registry)
    records = [SummaryRecord(label="AAPL", track="tech", scraped_text="Body text")]

    async def fake_generate(records, summarizer_name):
        return [
            SummaryRecord(
                label="AAPL",
                track="tech",
                scraped_text="Body text",
                summary="Summary one. Summary two.",
                summarizer_model=summarizer_name,
            )
        ]

    with (
        patch.object(harness, "generate_summaries", side_effect=fake_generate),
        patch.object(
            harness,
            "evaluate_records",
            return_value=[{
                "judge_model": registry.default_for("judges").name,
                "metrics": {},
                "label": "AAPL",
                "track": "tech",
                "summarizer_model": registry.default_for("summarizers").name,
                "summary": "Summary one. Summary two.",
            }],
        ) as mock_eval,
    ):
        results = asyncio.run(harness.run_mode(records, mode="smoke"))

    assert len(results) == 1
    mock_eval.assert_called_once()
    assert mock_eval.call_args.args[1] == registry.default_for("judges").name
