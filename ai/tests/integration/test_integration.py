import json
from unittest.mock import patch


class TestPipelineIntegration:
    def test_happy_path_scrape_to_json(self, tmp_path, mock_openai_client, canned_track_news):
        out_dir = tmp_path / "processed"
        out_dir.mkdir(parents=True)
        out_path = out_dir / "news_summaries.json"

        async def fake_scrape_all(session, ticker, company_name=None):
            return canned_track_news.get(ticker, "")

        with (
            patch("ai.pipeline.generate_news_tooltips.get_output_path", return_value=str(out_path)),
            patch("ai.pipeline.news_summarizer.OpenAICompatibleClient", return_value=mock_openai_client),
            patch("ai.pipeline.news_scraper.NewsScraper.scrape_all", side_effect=fake_scrape_all),
            patch("sys.argv", ["generate_news_tooltips", "--test-mode", "--summarizer-model", "local-qwen2.5-7b"]),
        ):
            from ai.pipeline.generate_news_tooltips import main

            main()

        assert out_path.exists()
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert len(data) > 0
        for item in data:
            assert "label" in item
            assert "summary" in item
            assert "track" in item
            assert "accessed_at" in item
            assert item["summarizer_model"] == "local-qwen2.5-7b"

    def test_scraper_failure_scenario(self, tmp_path):
        out_path = tmp_path / "empty.json"
        with (
            patch("ai.pipeline.generate_news_tooltips.get_output_path", return_value=str(out_path)),
            patch("ai.pipeline.news_scraper.NewsScraper.scrape_all", return_value=""),
            patch("ai.pipeline.news_summarizer.NewsSummarizer.generate_batch_summaries") as mock_summarize,
            patch("sys.argv", ["generate_news_tooltips", "--test-mode"]),
        ):
            from ai.pipeline.generate_news_tooltips import main

            main()

        mock_summarize.assert_not_called()
