#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.pipeline.summary_eval import SummaryEvalHarness, load_records, write_results


def parse_csv_arg(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Run DeepEval summary smoke or matrix mode.")
    parser.add_argument("--input", required=True, help="Path to a JSON file with scraped_text entries.")
    parser.add_argument("--output", default="ai/artifacts/summary_eval_results.json", help="Output JSON path.")
    parser.add_argument("--mode", choices=["smoke", "matrix"], default="smoke")
    parser.add_argument("--summarizers", help="Comma-separated summarizer registry names.")
    parser.add_argument("--judges", help="Comma-separated judge registry names.")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    load_dotenv(REPO_ROOT / "ai" / "pipeline" / ".env")

    harness = SummaryEvalHarness()
    records = load_records(args.input)
    results = await harness.run_mode(
        records,
        mode=args.mode,
        summarizer_names=parse_csv_arg(args.summarizers),
        judge_names=parse_csv_arg(args.judges),
    )
    write_results(results, args.output)
    print(f"Wrote {len(results)} eval rows to {Path(args.output)}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
