from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from arsenic_workflow.ris_ingest import (
    DEFAULT_DOWNLOAD_URL,
    DEFAULT_RIS_PATH,
    DEFAULT_SCREENING_PROMPT,
    download_raw_pdfs,
    initialize_literature_index_from_ris,
    load_literature_index,
    run_screening,
    write_literature_index,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RIS -> raw PDF -> Qwen screening workflow.")
    parser.add_argument("project_root", nargs="?", default=str(ROOT), help="repository root")
    parser.add_argument("--ris", default=str(DEFAULT_RIS_PATH), help="RIS file path relative to project root")
    parser.add_argument("--url", default=DEFAULT_DOWNLOAD_URL, help="PDF download URL")
    parser.add_argument("--screening-prompt", default=str(DEFAULT_SCREENING_PROMPT), help="screening prompt path")
    parser.add_argument("--skip-download", action="store_true", help="build the index without downloading PDFs")
    parser.add_argument("--skip-screening", action="store_true", help="skip Qwen screening")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = Path(args.project_root)
    index_path = initialize_literature_index_from_ris(root, ris_path=args.ris, pdf_url=args.url)
    index = load_literature_index(root)
    if not args.skip_download:
        index = download_raw_pdfs(root, index)
        write_literature_index(root, index.to_dict(orient="records"))
    if not args.skip_screening:
        index = run_screening(root, index, prompt_path=args.screening_prompt)
        write_literature_index(root, index.to_dict(orient="records"))
    print(f"Literature index: {index_path}")
    print(index.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
