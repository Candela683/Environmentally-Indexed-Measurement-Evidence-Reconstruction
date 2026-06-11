from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from arsenic_workflow.devtools.generate_synthetic_pdf import generate_synthetic_pdf
from arsenic_workflow.synthetic_pdf import PDF_RELATIVE_PATH
from arsenic_workflow.synthetic_pdf import (
    prepare_synthetic_database,
    prepare_synthetic_database_with_qwen,
    run_synthetic_pdf_demo,
)


def parse_args(argv: list[str]) -> tuple[Path, bool, Path, int, str | None]:
    use_qwen = False
    prompt_template = Path("templates") / "prompt_v1.txt"
    qwen_runs = 2
    model = None
    positional = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--qwen":
            use_qwen = True
        elif arg == "--prompt-template":
            index += 1
            if index >= len(argv):
                raise ValueError("Missing value after --prompt-template")
            prompt_template = Path(argv[index])
        elif arg == "--qwen-runs":
            index += 1
            if index >= len(argv):
                raise ValueError("Missing value after --qwen-runs")
            qwen_runs = int(argv[index])
        elif arg == "--model":
            index += 1
            if index >= len(argv):
                raise ValueError("Missing value after --model")
            model = argv[index]
        else:
            positional.append(arg)
        index += 1
    run_root = Path(positional[0]).resolve() if positional else ROOT
    return run_root, use_qwen, prompt_template, qwen_runs, model


if __name__ == "__main__":
    run_root, use_qwen, prompt_template, qwen_runs, model = parse_args(sys.argv[1:])
    pdf_path = run_root / PDF_RELATIVE_PATH
    if not pdf_path.exists():
        pdf_path = generate_synthetic_pdf(pdf_path)
    print(f"Generated synthetic PDF: {pdf_path}")
    if use_qwen:
        prepared = prepare_synthetic_database_with_qwen(
            run_root,
            model=model,
            prompt_template_path=prompt_template,
            runs=qwen_runs,
        )
    else:
        prepared = prepare_synthetic_database(run_root)
    print("Prepared synthetic inputs:")
    for name, path in prepared.items():
        print(f"- {name}: {path}")
    outputs = run_synthetic_pdf_demo(
        run_root,
        use_qwen=use_qwen,
        model=model,
        prepare=False,
        prompt_template_path=prompt_template,
        qwen_runs=qwen_runs,
    )
    print("Synthetic PDF demo finished. Outputs:")
    for name, path in outputs.items():
        print(f"- {name}: {path}")
