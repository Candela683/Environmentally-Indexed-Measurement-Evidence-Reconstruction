from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from arsenic_workflow.source_parse import parse_all_article_pdfs


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse all article source PDFs into text and page images.")
    parser.add_argument("project_root", nargs="?", default=str(ROOT), help="repository root")
    parser.add_argument("--dpi", type=int, default=180, help="page image render DPI")
    parser.add_argument("--no-overwrite", action="store_true", help="keep existing parsed text/images")
    parser.add_argument("--no-ocr-fallback", action="store_true", help="do not call OCR when native PDF text is abnormal")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    results = parse_all_article_pdfs(
        args.project_root,
        dpi=args.dpi,
        overwrite=not args.no_overwrite,
        ocr_on_abnormal=not args.no_ocr_fallback,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
