from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from arsenic_workflow.ris_ingest import DEFAULT_DOWNLOAD_URL, DEFAULT_RIS_PATH, prepare_pdf_unit_from_example_ris


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse example.ris and prepare one PDF unit.")
    parser.add_argument("project_root", nargs="?", default=str(ROOT), help="repository root")
    parser.add_argument("--ris", default=str(DEFAULT_RIS_PATH), help="RIS file path relative to project root")
    parser.add_argument("--url", default=DEFAULT_DOWNLOAD_URL, help="PDF download URL")
    parser.add_argument("--unit-name", default="[yes]+example", help="PDF unit folder name")
    parser.add_argument("--no-download", action="store_true", help="create metadata only")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    paths = prepare_pdf_unit_from_example_ris(
        args.project_root,
        ris_path=args.ris,
        download_url=args.url,
        unit_name=args.unit_name,
        download_pdf=not args.no_download,
    )
    print("Prepared RIS-derived PDF unit:")
    for key, value in paths.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
