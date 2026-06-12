from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from arsenic_workflow.harmonize import UNIT_FACTORS_TO_MG_KG, normalize_unit, parse_number
from arsenic_workflow.qwen_extraction import (
    build_extraction_prompt,
    call_qwen,
    extract_json_payload,
    load_extraction_prompt_spec,
    qwen_json_to_candidate_records,
    save_qwen_artifacts,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run two Qwen extraction passes and keep concentration-agreeing records.")
    parser.add_argument("project_root", nargs="?", default=str(ROOT), help="repository root")
    parser.add_argument("--article-id", action="append", help="limit to one or more article ids")
    parser.add_argument(
        "--prompt-yaml",
        default="config/prompts/extraction/extraction_v1.yaml",
        help="extraction prompt YAML relative to project root",
    )
    parser.add_argument("--runs", type=int, default=None, help="override number of extraction runs from prompt YAML")
    return parser.parse_args(argv)


def article_dirs(project_root: Path, article_ids: list[str] | None) -> list[Path]:
    articles_root = project_root / "data" / "articles"
    if article_ids:
        return [articles_root / article_id for article_id in article_ids]
    return sorted(path for path in articles_root.iterdir() if path.is_dir())


def selected_text_path(article_dir: Path) -> Path:
    manifest_path = article_dir / "source" / "extracted_text" / "text_priority_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing text priority manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = manifest.get("selected_text") or {}
    selected_path = selected.get("path")
    if not selected_path:
        raise FileNotFoundError(f"No non-empty selected text file for article: {article_dir.name}")
    return article_dir / selected_path


def concentration_key(row: pd.Series) -> str:
    value = row.get("total_arsenic", "")
    unit = normalize_unit(row.get("arsenic_unit", ""))
    raw = parse_number(value)
    if isinstance(unit, str) and unit in UNIT_FACTORS_TO_MG_KG and pd.notna(raw):
        mg_kg_ww = raw * UNIT_FACTORS_TO_MG_KG[unit]
        return f"mgkgww:{mg_kg_ww:.12g}"
    return f"raw:{str(value).strip().lower()}|unit:{str(unit).strip().lower()}"


def concentration_consensus(run_frames: list[pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    combined = pd.concat(run_frames, ignore_index=True) if run_frames else pd.DataFrame()
    if combined.empty:
        return combined, pd.DataFrame()
    combined = combined.copy()
    combined["concentration_key"] = combined.apply(concentration_key, axis=1)
    key_counts = combined.groupby("concentration_key")["candidate_run"].nunique()
    agreed_keys = set(key_counts[key_counts >= 2].index)
    agreed = combined[combined["concentration_key"].isin(agreed_keys)].copy()
    agreed = agreed.sort_values(["concentration_key", "candidate_run", "record_id"]).drop_duplicates("concentration_key")
    qc = (
        combined.groupby("concentration_key", dropna=False)
        .agg(
            n_rows=("concentration_key", "size"),
            n_runs=("candidate_run", "nunique"),
            runs=("candidate_run", lambda values: "|".join(sorted(set(map(str, values))))),
            total_arsenic_values=("total_arsenic", lambda values: "|".join(sorted(set(map(str, values))))),
            arsenic_units=("arsenic_unit", lambda values: "|".join(sorted(set(map(str, values))))),
        )
        .reset_index()
    )
    qc["concentration_agreement"] = qc["concentration_key"].isin(agreed_keys)
    return agreed, qc


def run_article(project_root: Path, article_dir: Path, prompt_spec: dict[str, object], runs: int) -> dict[str, object]:
    source_pdf = article_dir / "source" / f"{article_dir.name}.pdf"
    if not source_pdf.exists():
        return {"article_id": article_dir.name, "status": "missing_source_file", "source_file": str(source_pdf)}

    text_path = selected_text_path(article_dir)
    article_text = text_path.read_text(encoding="utf-8")
    prompt_file = Path(str(prompt_spec["prompt_file"]))
    enable_thinking = bool(prompt_spec["enable_thinking"])
    run_frames = []
    artifacts = []
    for run_number in range(1, runs + 1):
        prompt = build_extraction_prompt(article_text, project_root=project_root, template_relative_path=prompt_file)
        response = call_qwen(prompt, project_root=project_root, enable_thinking=enable_thinking)
        payload = extract_json_payload(response)
        candidates = qwen_json_to_candidate_records(payload, candidate_run=f"QWEN_RUN_{run_number:02d}", source_id=article_dir.name)
        paths = save_qwen_artifacts(
            article_dir,
            prompt_file,
            prompt,
            response,
            payload,
            candidates,
            run_number=run_number,
        )
        run_frames.append(candidates)
        artifacts.append({key: str(value) for key, value in paths.items()})

    agreed, qc = concentration_consensus(run_frames)
    version_dir = article_dir / "source" / str(prompt_spec["version"])
    final_dir = version_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    agreed_path = final_dir / "concentration_consensus_records.csv"
    qc_path = final_dir / "concentration_consensus_qc.csv"
    selected_path = final_dir / "selected_text_for_extraction.json"
    agreed.to_csv(agreed_path, index=False, encoding="utf-8")
    qc.to_csv(qc_path, index=False, encoding="utf-8")
    selected_path.write_text(
        json.dumps(
            {
                "article_id": article_dir.name,
                "selected_text_path": str(text_path.relative_to(article_dir)),
                "prompt_yaml": str(prompt_spec["yaml_path"]),
                "prompt_version": prompt_spec["version"],
                "enable_thinking": enable_thinking,
                "runs": runs,
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "article_id": article_dir.name,
        "status": "extracted",
        "selected_text": str(text_path),
        "n_consensus_records": int(len(agreed)),
        "consensus_records": str(agreed_path),
        "consensus_qc": str(qc_path),
        "artifacts": artifacts,
    }


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root)
    prompt_spec = load_extraction_prompt_spec(project_root=project_root, prompt_yaml_path=args.prompt_yaml)
    runs = args.runs if args.runs is not None else int(prompt_spec.get("runs", 2))
    results = [run_article(project_root, article_dir, prompt_spec, runs=runs) for article_dir in article_dirs(project_root, args.article_id)]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
