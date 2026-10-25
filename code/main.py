"""Main entry point for Ghost Data Still Exists deletion audit agent.

Usage:
    python code/main.py [--dataset-dir DATASET_DIR] [--output OUTPUT_PATH] [--sample-only] [--cases CASES_CSV] [--limit N]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Add repo root and code directory to sys.path
CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

try:
    from config import (
        ALLOWED_STATUSES,
        DATASET_DIR,
        EVALUATION_DIR,
        LOG_FILE,
        MODEL_NAME,
        OUTPUT_CSV,
    )
except ImportError:
    from code.config import (
        ALLOWED_STATUSES,
        DATASET_DIR,
        EVALUATION_DIR,
        LOG_FILE,
        MODEL_NAME,
        OUTPUT_CSV,
    )

from code.agent.llm_client import GeminiClient
from code.agent.pipeline import DeletionAuditPipeline, CaseResult
from code.utils.csv_io import read_csv_rows, write_csv_rows

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("audit_agent.main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ghost Data Still Exists — AI Deletion Audit Agent"
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DATASET_DIR,
        help="Path to dataset directory containing CSVs and evidence",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_CSV,
        help="Path to output.csv submission file",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=None,
        help="Explicit path to requests CSV (overrides default deletion_requests.csv)",
    )
    parser.add_argument(
        "--sample-only",
        action="store_true",
        help="Run only on sample_deletion_requests.csv for testing/validation",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of cases to process (for debugging)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=MODEL_NAME,
        help="Gemini model name to use for LLM evaluations",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM calls and rely strictly on deterministic rule evaluation",
    )
    parser.add_argument(
        "--usage-report",
        type=Path,
        default=EVALUATION_DIR / "usage_report.md",
        help="Path to export the token and cost analysis report",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logger.info("=" * 60)
    logger.info("Ghost Data Still Exists — Deletion Audit Agent Pipeline")
    logger.info("=" * 60)
    logger.info("Dataset Directory: %s", args.dataset_dir)
    logger.info("Target Output:    %s", args.output)

    # 1. Determine input requests file
    if args.cases:
        cases_file = args.cases
    elif args.sample_only:
        cases_file = args.dataset_dir / "sample_deletion_requests.csv"
    else:
        cases_file = args.dataset_dir / "deletion_requests.csv"

    if not cases_file.is_file():
        logger.error("Cases file not found: %s", cases_file)
        sys.exit(1)

    logger.info("Loading requests from: %s", cases_file)
    cases = read_csv_rows(cases_file)
    total_loaded = len(cases)
    logger.info("Loaded %d cases.", total_loaded)

    if args.limit and args.limit > 0:
        cases = cases[:args.limit]
        logger.info("Processing limited to first %d cases.", len(cases))

    # 2. Initialize Gemini Client & Pipeline
    llm_client = GeminiClient(model_name=args.model)
    use_llm = not args.no_llm

    pipeline = DeletionAuditPipeline(
        dataset_dir=args.dataset_dir,
        llm_client=llm_client,
        use_llm=use_llm,
    )
    pipeline.load()

    # 3. Process cases
    start_time = time.time()
    results: list[CaseResult] = pipeline.process_all(cases, show_progress=True)
    duration = time.time() - start_time

    logger.info("Processed %d cases in %.2f seconds (%.2f s/case).", len(results), duration, duration / max(1, len(results)))

    # 4. Sort results by case_id
    def case_sort_key(res: CaseResult) -> int:
        digits = "".join(filter(str.isdigit, res.case_id))
        return int(digits) if digits else 0

    sorted_results = sorted(results, key=case_sort_key)

    # 5. Compile output rows
    output_rows = [res.to_csv_row() for res in sorted_results]

    # Validate output rows
    status_counts: dict[str, int] = {}
    for row in output_rows:
        st = row["deletion_status"]
        status_counts[st] = status_counts.get(st, 0) + 1
        if st not in ALLOWED_STATUSES:
            logger.warning("Unrecognized status '%s' in case %s", st, row["case_id"])

    # 6. Write output.csv
    logger.info("Writing results to %s...", args.output)
    write_csv_rows(
        filepath=args.output,
        rows=output_rows,
        fieldnames=["case_id", "deletion_status", "steps_json"],
    )
    logger.info("Successfully wrote %d rows to %s", len(output_rows), args.output)

    # 7. Export token usage and cost report
    logger.info("Exporting usage report to %s...", args.usage_report)
    llm_client.export_usage_report(output_path=args.usage_report)

    # 8. Print execution summary
    print("\n" + "=" * 60)
    print("AUDIT RUN SUMMARY")
    print("=" * 60)
    print(f"Total cases audited:  {len(output_rows)}")
    for status, count in sorted(status_counts.items()):
        pct = (count / len(output_rows)) * 100 if output_rows else 0
        print(f"  {status:<18}: {count:>4} ({pct:.1f}%)")
    print(f"Elapsed time:         {duration:.2f} seconds")
    print(f"Output saved to:      {args.output}")
    print(f"Usage report saved to:{args.usage_report}")
    print("=" * 60)


if __name__ == "__main__":
    main()
