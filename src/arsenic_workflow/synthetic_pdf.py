"""Synthetic PDF extraction and SQLite preparation for the end-to-end demo."""

from __future__ import annotations

import io
import re
import shutil
import sqlite3
from pathlib import Path

import pandas as pd

from .full_run import run_full_local
from .llm_config import load_dashscope_config
from .qwen_extraction import (
    TEMPLATE_RELATIVE_PATH,
    add_extraction_index,
    build_synthetic_extraction_prompt,
    call_qwen,
    extract_json_payload,
    prompt_version_from_template,
    qwen_json_to_candidate_records,
    save_qwen_artifacts,
)


SYNTHETIC_BUNDLE = Path("synthetic_bundle")
ARTICLE_FOLDER_NAME = "[yes]+synthetic_marine_arsenic_article"
ARTICLE_RELATIVE_DIR = SYNTHETIC_BUNDLE / "data_raw" / "literature" / "pdfs" / ARTICLE_FOLDER_NAME
PDF_FOLDER_RELATIVE_DIR = ARTICLE_RELATIVE_DIR / "pdf"
PDF_RELATIVE_PATH = PDF_FOLDER_RELATIVE_DIR / "synthetic_arsenic_article.pdf"
DOI_RELATIVE_PATH = PDF_FOLDER_RELATIVE_DIR / "doi.txt"
SQLITE_RELATIVE_PATH = SYNTHETIC_BUNDLE / "data_raw" / "databases" / "sqlite" / "synthetic_arsenic_reconstruction.sqlite"
OUTPUT_RELATIVE_DIR = SYNTHETIC_BUNDLE / "outputs"
REVIEW_RELATIVE_DIR = SYNTHETIC_BUNDLE / "review_tables"


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """Extract all text from the synthetic PDF."""

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Missing synthetic PDF: {pdf_path}")
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if "BEGIN_SYNTHETIC_TABLE" in text:
            return text
    except ImportError:
        pass

    raw = pdf_path.read_bytes().decode("latin-1", errors="ignore")
    strings = re.findall(r"\((.*?)\)\s*Tj", raw, flags=re.DOTALL)
    return "\n".join(s.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\") for s in strings)


def extract_synthetic_table(pdf_text: str) -> pd.DataFrame:
    """Extract the CSV-like synthetic table embedded in the PDF text."""

    start = "BEGIN_SYNTHETIC_TABLE"
    end = "END_SYNTHETIC_TABLE"
    if start not in pdf_text or end not in pdf_text:
        raise ValueError("Synthetic table markers were not found in the PDF text.")
    table_text = pdf_text.split(start, 1)[1].split(end, 1)[0].strip()
    table_text = "\n".join(line.strip() for line in table_text.splitlines() if line.strip())
    return pd.read_csv(io.StringIO(table_text))


def build_candidate_records(table: pd.DataFrame) -> pd.DataFrame:
    """Convert extracted table rows to candidate records."""

    df = table.copy()
    df["marine_organism"] = True
    df["source_support"] = True
    df["manual_keep"] = df["candidate_run"].ne("B")
    df["notes"] = "synthetic pdf extraction test"
    df["known_organic_as_mg_per_kg_ww"] = (
        pd.to_numeric(df["arsenobetaine_mg_per_kg_ww"], errors="coerce")
        + pd.to_numeric(df["arsenosugars_mg_per_kg_ww"], errors="coerce")
    )
    df["known_inorganic_as_mg_per_kg_ww"] = (
        pd.to_numeric(df["as_iii_mg_per_kg_ww"], errors="coerce")
        + pd.to_numeric(df["as_v_mg_per_kg_ww"], errors="coerce")
    )
    return df


def synthetic_taxonomy() -> pd.DataFrame:
    """Return accepted taxonomy for the synthetic organisms."""

    return pd.DataFrame(
        [
            ["Mytilus edulis", "mussel", "Mytilus edulis", "Animalia", "Mollusca", "Bivalvia", "Mytilida", "Mytilidae", "Mytilus", "Mytilus edulis"],
            ["Sargassum fusiforme", "brown seaweed", "Sargassum fusiforme", "Chromista", "Ochrophyta", "Phaeophyceae", "Fucales", "Sargassaceae", "Sargassum", "Sargassum fusiforme"],
            ["Gadus morhua", "cod", "Gadus morhua", "Animalia", "Chordata", "Actinopteri", "Gadiformes", "Gadidae", "Gadus", "Gadus morhua"],
            ["Crassostrea gigas", "oyster", "Magallana gigas", "Animalia", "Mollusca", "Bivalvia", "Ostreida", "Ostreidae", "Magallana", "Magallana gigas"],
        ],
        columns=["scientific_name", "common_name", "accepted_name", "kingdom", "phylum", "class", "order", "family", "genus", "species"],
    )


def synthetic_environment() -> pd.DataFrame:
    """Return a small month-specific environmental table for the synthetic records."""

    return pd.DataFrame(
        [
            [36.00, 140.00, 2020, 7, 33.8, 20.5, 211, 0.8, 18],
            [-18.00, 148.00, 2019, 3, 35.1, 27.2, 198, 0.3, 24],
            [45.50, -62.00, 2021, 9, 31.2, 11.0, 245, 1.9, 35],
            [-33.50, 18.50, 2018, 2, 34.7, 17.8, 220, 1.1, 28],
        ],
        columns=[
            "env_latitude",
            "env_longitude",
            "year",
            "month",
            "salinity",
            "temperature_c",
            "dissolved_oxygen",
            "chlorophyll_a",
            "mixed_layer_depth",
        ],
    )


def synthetic_validation() -> pd.DataFrame:
    """Return validation labels for the synthetic records."""

    return pd.DataFrame(
        [
            ["SYN-R001", "SYN001", "true_positive", "", "supported synthetic table row"],
            ["SYN-R002", "SYN001", "true_positive", "", "supported synthetic table row"],
            ["SYN-R003", "SYN001", "true_positive", "", "supported synthetic table row"],
            ["SYN-R004", "SYN001", "true_positive", "", "dry-weight imputed moisture example"],
        ],
        columns=["record_id", "source_id", "validation_status", "error_class", "comment"],
    )


def synthetic_sources() -> pd.DataFrame:
    """Return source metadata for the synthetic article."""

    return pd.DataFrame(
        [
            {
                "source_id": "SYN001",
                "doi": "10.0000/synthetic.arsenic.demo",
                "title": "Synthetic Marine Arsenic Measurements In Example Organisms",
                "year": 2026,
                "screening_status": "include",
            }
        ]
    )


def write_synthetic_sqlite(project_root: str | Path, candidate_records: pd.DataFrame) -> Path:
    """Write all prepared synthetic tables into the relative SQLite path."""

    project_root = Path(project_root)
    db_path = project_root / SQLITE_RELATIVE_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        synthetic_sources().to_sql("sources", conn, if_exists="replace", index=False)
        candidate_records.to_sql("candidate_records", conn, if_exists="replace", index=False)
        synthetic_taxonomy().to_sql("taxonomy_resolved", conn, if_exists="replace", index=False)
        synthetic_environment().to_sql("environment_monthly", conn, if_exists="replace", index=False)
        synthetic_validation().to_sql("validation", conn, if_exists="replace", index=False)
    return db_path


def version_dir_for_prompt(project_root: str | Path, prompt_template_path: str | Path = TEMPLATE_RELATIVE_PATH) -> Path:
    """Return the article PDF subfolder for one prompt version."""

    return Path(project_root) / PDF_FOLDER_RELATIVE_DIR / prompt_version_from_template(prompt_template_path)


def pdf_unit_dir(project_root: str | Path) -> Path:
    """Return the PDF-centered data unit directory for the synthetic article."""

    return Path(project_root) / PDF_FOLDER_RELATIVE_DIR


def review_tables_dir(project_root: str | Path) -> Path:
    """Return the project-level review table directory outside PDF folders."""

    return Path(project_root) / REVIEW_RELATIVE_DIR


def write_pdf_unit_metadata(project_root: str | Path) -> dict[str, Path]:
    """Write PDF-unit metadata that is present before extraction."""

    pdf_dir = pdf_unit_dir(project_root)
    metadata_dir = pdf_dir / "source_metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    doi_path = pdf_dir / "doi.txt"
    source_id_path = metadata_dir / "source_id.txt"
    if not doi_path.exists():
        doi_path.write_text("10.0000/synthetic.arsenic.demo\n", encoding="utf-8")
    if not source_id_path.exists():
        source_id_path.write_text("SYN001\n", encoding="utf-8")
    return {"doi": doi_path, "source_id": source_id_path}


def save_final_candidate_artifacts(version_dir: str | Path, candidates: pd.DataFrame) -> dict[str, Path]:
    """Save the final indexed candidate table used for SQLite ingestion."""

    version_dir = Path(version_dir)
    final_dir = version_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "final_candidate_records": final_dir / "final_candidate_records.csv",
        "final_indexed_records": final_dir / "final_indexed_records.csv",
    }
    candidates.to_csv(paths["final_candidate_records"], index=False, encoding="utf-8")
    candidates.to_csv(paths["final_indexed_records"], index=False, encoding="utf-8")
    return paths


def _pdf_version_label(version_dir: str | Path) -> str:
    return Path(version_dir).name


def aggregate_extracted_records(project_root: str | Path, version_dir: str | Path) -> dict[str, Path]:
    """Combine final extraction CSVs from all PDF units for one prompt version."""

    project_root = Path(project_root)
    version_dir = Path(version_dir)
    version_label = _pdf_version_label(version_dir)
    extracted_dir = review_tables_dir(project_root) / "extracted_data"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    pdf_roots = project_root / SYNTHETIC_BUNDLE / "data_raw" / "literature" / "pdfs"
    frames = []
    if pdf_roots.exists():
        for pdf_dir in sorted(pdf_roots.glob("*/pdf")):
            final_path = pdf_dir / version_label / "final" / "final_indexed_records.csv"
            if final_path.exists():
                frame = pd.read_csv(final_path)
                frame.insert(0, "pdf_unit_folder", str(pdf_dir))
                frame.insert(1, "article_folder", pdf_dir.parent.name)
                frames.append(frame)
    if not frames:
        final_path = version_dir / "final" / "final_indexed_records.csv"
        if final_path.exists():
            frame = pd.read_csv(final_path)
            frame.insert(0, "pdf_unit_folder", str(version_dir.parent))
            frame.insert(1, "article_folder", version_dir.parent.parent.name)
            frames.append(frame)
    if frames:
        combined = pd.concat(frames, ignore_index=True)
    else:
        combined = pd.DataFrame()

    paths = {
        "review_extracted_records": extracted_dir / f"{version_label}_extracted_records.csv",
        "review_latest_extracted_records": extracted_dir / "latest_extracted_records.csv",
    }
    combined.to_csv(paths["review_extracted_records"], index=False, encoding="utf-8")
    combined.to_csv(paths["review_latest_extracted_records"], index=False, encoding="utf-8")
    return paths


def archive_project_review_outputs(project_root: str | Path, version_dir: str | Path, outputs: dict[str, Path]) -> dict[str, Path]:
    """Copy stage outputs into project-level review folders outside PDF units."""

    project_root = Path(project_root)
    archived: dict[str, Path] = {}
    archived.update(aggregate_extracted_records(project_root, version_dir))
    folders = {
        "coordinate_qc": "geographic_mapping",
        "species_matched_records": "species_matching",
        "model_ready_records": "environment_variable_matching",
        "validation_metrics": "validation",
        "validation_error_classes": "validation",
    }
    review_dir = review_tables_dir(project_root)
    all_dir = review_dir / "complete_outputs"
    all_dir.mkdir(parents=True, exist_ok=True)
    for name, source in outputs.items():
        source = Path(source)
        if not source.exists():
            continue
        target = all_dir / source.name
        shutil.copy2(source, target)
        archived[f"archived_{name}"] = target
        if name in folders:
            specific_dir = review_dir / folders[name]
            specific_dir.mkdir(parents=True, exist_ok=True)
            specific_target = specific_dir / source.name
            shutil.copy2(source, specific_target)
            archived[f"{folders[name]}_{name}"] = specific_target
    manual_paths = archive_manual_review_if_validated(project_root, version_dir, outputs)
    archived.update(manual_paths)
    return archived


def validation_passed(outputs: dict[str, Path]) -> bool:
    """Return whether demo validation is clean enough for manual-review export."""

    metrics_path = outputs.get("validation_metrics")
    if metrics_path is None or not Path(metrics_path).exists():
        return False
    metrics = pd.read_csv(metrics_path)
    if metrics.empty:
        return False
    row = metrics.iloc[0]
    return (
        int(row.get("true_positive", 0)) > 0
        and int(row.get("false_positive", 0)) == 0
        and int(row.get("false_negative", 0)) == 0
    )


def archive_manual_review_if_validated(project_root: str | Path, version_dir: str | Path, outputs: dict[str, Path]) -> dict[str, Path]:
    """Export reviewed extraction CSVs only after validation passes."""

    if not validation_passed(outputs):
        return {}
    project_root = Path(project_root)
    version_dir = Path(version_dir)
    review_dir = review_tables_dir(project_root) / "extracted_data" / "validated_for_manual_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    archived: dict[str, Path] = {}
    for name in ["candidate_qc", "harmonized_records"]:
        source = outputs.get(name)
        if source is None or not Path(source).exists():
            continue
        target = review_dir / Path(source).name
        shutil.copy2(source, target)
        archived[f"manual_review_{name}"] = target
    final_source = version_dir / "final" / "final_indexed_records.csv"
    if final_source.exists():
        target = review_dir / f"{_pdf_version_label(version_dir)}_validated_extraction_for_manual_review.csv"
        shutil.copy2(final_source, target)
        archived["manual_review_validated_extraction"] = target
    return archived


def prepare_synthetic_database(project_root: str | Path) -> dict[str, Path]:
    """Extract the synthetic PDF and create the SQLite database."""

    project_root = Path(project_root)
    pdf_path = project_root / PDF_RELATIVE_PATH
    text = extract_text_from_pdf(pdf_path)
    table = extract_synthetic_table(text)
    article_dir = project_root / ARTICLE_RELATIVE_DIR
    pdf_dir = pdf_unit_dir(project_root)
    (pdf_dir / "extracted_text").mkdir(parents=True, exist_ok=True)
    (pdf_dir / "extracted_tables").mkdir(parents=True, exist_ok=True)
    metadata_paths = write_pdf_unit_metadata(project_root)
    (pdf_dir / "extracted_text" / "extracted_text.txt").write_text(text, encoding="utf-8")
    table.to_csv(pdf_dir / "extracted_tables" / "synthetic_measurements.csv", index=False, encoding="utf-8")
    candidates = build_candidate_records(table)
    local_version_dir = pdf_dir / "local"
    indexed = add_extraction_index(candidates, "local", 1)
    (local_version_dir / "parsed_csv").mkdir(parents=True, exist_ok=True)
    (local_version_dir / "indexed_csv").mkdir(parents=True, exist_ok=True)
    candidates.to_csv(local_version_dir / "parsed_csv" / "run_01_parsed_records.csv", index=False, encoding="utf-8")
    indexed.to_csv(local_version_dir / "indexed_csv" / "run_01_indexed_records.csv", index=False, encoding="utf-8")
    final_paths = save_final_candidate_artifacts(local_version_dir, indexed)
    db_path = write_synthetic_sqlite(project_root, indexed)
    return {
        "article_dir": article_dir,
        "version_dir": local_version_dir,
        "pdf": pdf_path,
        "doi": metadata_paths["doi"],
        "source_id": metadata_paths["source_id"],
        "extracted_text": pdf_dir / "extracted_text" / "extracted_text.txt",
        "extracted_table": pdf_dir / "extracted_tables" / "synthetic_measurements.csv",
        "sqlite": db_path,
        **final_paths,
    }


def prepare_synthetic_database_with_qwen(
    project_root: str | Path,
    model: str | None = None,
    prompt_template_path: str | Path = TEMPLATE_RELATIVE_PATH,
    runs: int = 2,
) -> dict[str, Path]:
    """Use Qwen to extract candidate records from the synthetic PDF, then create SQLite."""

    project_root = Path(project_root)
    prompt_template_path = Path(prompt_template_path)
    pdf_path = project_root / PDF_RELATIVE_PATH
    text = extract_text_from_pdf(pdf_path)
    article_dir = project_root / ARTICLE_RELATIVE_DIR
    pdf_dir = pdf_unit_dir(project_root)
    (pdf_dir / "extracted_text").mkdir(parents=True, exist_ok=True)
    metadata_paths = write_pdf_unit_metadata(project_root)
    (pdf_dir / "extracted_text" / "extracted_text.txt").write_text(text, encoding="utf-8")

    all_candidates = []
    artifact_paths: dict[str, Path] = {}
    version_dir = version_dir_for_prompt(project_root, prompt_template_path)
    actual_model = model or load_dashscope_config(project_root=Path(__file__).resolve().parents[2]).extraction_model
    for run_number in range(1, runs + 1):
        prompt = build_synthetic_extraction_prompt(
            text,
            project_root=Path(__file__).resolve().parents[2],
            template_relative_path=prompt_template_path,
        )
        response = call_qwen(prompt, model=actual_model, project_root=Path(__file__).resolve().parents[2])
        payload = extract_json_payload(response)
        candidates = qwen_json_to_candidate_records(payload, candidate_run=f"QWEN_RUN_{run_number:02d}")
        indexed = add_extraction_index(candidates, prompt_version_from_template(prompt_template_path), run_number)
        all_candidates.append(indexed)
        run_paths = save_qwen_artifacts(
            article_dir,
            prompt_template_path,
            prompt,
            response,
            payload,
            candidates,
            run_number=run_number,
            model=actual_model,
        )
        artifact_paths.update({f"run_{run_number:02d}_{key}": value for key, value in run_paths.items()})
    final_candidates = pd.concat(all_candidates, ignore_index=True) if all_candidates else pd.DataFrame()
    final_paths = save_final_candidate_artifacts(version_dir, final_candidates)
    db_path = write_synthetic_sqlite(project_root, final_candidates)
    return {
        "article_dir": article_dir,
        "version_dir": version_dir,
        "pdf": pdf_path,
        "doi": metadata_paths["doi"],
        "source_id": metadata_paths["source_id"],
        "extracted_text": pdf_dir / "extracted_text" / "extracted_text.txt",
        "sqlite": db_path,
        **artifact_paths,
        **final_paths,
    }


def run_synthetic_pdf_demo(
    project_root: str | Path,
    use_qwen: bool = False,
    model: str | None = None,
    prepare: bool = True,
    prompt_template_path: str | Path = TEMPLATE_RELATIVE_PATH,
    qwen_runs: int = 2,
) -> dict[str, Path]:
    """Prepare SQLite from the synthetic PDF and run the full workflow."""

    project_root = Path(project_root)
    version_dir = version_dir_for_prompt(project_root, prompt_template_path) if use_qwen else project_root / PDF_FOLDER_RELATIVE_DIR / "local"
    if prepare:
        if use_qwen:
            prepared = prepare_synthetic_database_with_qwen(
                project_root,
                model=model,
                prompt_template_path=prompt_template_path,
                runs=qwen_runs,
            )
            version_dir = prepared["version_dir"]
        else:
            prepared = prepare_synthetic_database(project_root)
            version_dir = prepared["version_dir"]
    outputs = run_full_local(project_root / SYNTHETIC_BUNDLE, project_root / OUTPUT_RELATIVE_DIR)
    archived = archive_project_review_outputs(project_root, version_dir, outputs)
    return {**outputs, **archived}
