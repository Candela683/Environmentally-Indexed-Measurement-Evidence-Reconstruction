from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from arsenic_workflow.review_workspace import run_review_stage, run_review_workflow


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run staged manual-review CSV workflow.")
    parser.add_argument("project_root", nargs="?", default=str(ROOT), help="repository root")
    parser.add_argument(
        "--stage",
        default="all",
        choices=[
            "all",
            "extraction_aggregation",
            "measurement_harmonization",
            "worms_taxonomy_matching",
            "geographic_review",
            "environment_matching",
            "final_output",
        ],
        help="stage to run; default runs all stages in order",
    )
    parser.add_argument("--config", default="config/review_stages.yaml", help="review-stage config path")
    return parser.parse_args(argv)


def stringify_paths(value):
    if isinstance(value, dict):
        return {key: stringify_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [stringify_paths(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = Path(args.project_root)
    if args.stage == "all":
        result = run_review_workflow(root, config_path=args.config)
    else:
        result = run_review_stage(root, args.stage, config_path=args.config)
    print(json.dumps(stringify_paths(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
