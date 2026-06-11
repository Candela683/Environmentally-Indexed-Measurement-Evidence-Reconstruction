"""Full local rerun helpers for user-supplied files and databases."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .env_match import attach_nearest_environment
from .extraction_qc import classify_candidate_records, compare_duplicate_runs, summarize_field_completeness
from .geocoding import flag_coordinate_quality
from .harmonize import harmonize_records
from .io import read_table, write_csv
from .modeling import (
    fit_environment_models,
    spearman_environment_correlation,
    summarize_taxonomic_variance,
    taxon_environment_response,
)
from .speciation import summarize_speciation
from .taxonomy import attach_taxonomy
from .validation import error_class_summary, validation_metrics


TABLE_SUFFIXES = {".csv", ".tsv", ".jsonl", ".xlsx", ".xls", ".pkl", ".pickle"}
DB_SUFFIXES = {".sqlite", ".sqlite3", ".db"}


def _candidate_files(folder: Path, suffixes: set[str]) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in suffixes)


def _sqlite_files(project_root: Path) -> list[Path]:
    return _candidate_files(project_root / "data_raw" / "databases" / "sqlite", DB_SUFFIXES)


def _table_exists(db_path: Path, table_name: str) -> bool:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
    return row is not None


def _read_sqlite_table(project_root: Path, table_name: str) -> pd.DataFrame | None:
    for db_path in _sqlite_files(project_root):
        if _table_exists(db_path, table_name):
            with sqlite3.connect(db_path) as conn:
                return pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)
    return None


def _read_first_table(folder: Path, description: str) -> pd.DataFrame:
    files = _candidate_files(folder, TABLE_SUFFIXES)
    if not files:
        raise FileNotFoundError(
            f"Missing {description}. Expected at least one table file in: {folder}"
        )
    return read_table(files[0])


def load_candidate_records(project_root: str | Path) -> pd.DataFrame:
    """Load candidate records from SQLite or extraction files."""

    project_root = Path(project_root)
    from_db = _read_sqlite_table(project_root, "candidate_records")
    if from_db is not None:
        return from_db
    return _read_first_table(
        project_root / "data_raw" / "extraction" / "jsonl",
        "candidate records table or SQLite table candidate_records",
    )


def load_taxonomy_lookup(project_root: str | Path) -> pd.DataFrame:
    """Load resolved taxonomy from SQLite or taxonomy folders."""

    project_root = Path(project_root)
    from_db = _read_sqlite_table(project_root, "taxonomy_resolved")
    if from_db is not None:
        return from_db
    for folder in [
        project_root / "data_raw" / "taxonomy" / "manual_overrides",
        project_root / "data_raw" / "taxonomy" / "worms",
        project_root / "data_raw" / "taxonomy" / "gbif_backbone",
    ]:
        files = _candidate_files(folder, TABLE_SUFFIXES)
        if files:
            return read_table(files[0])
    raise FileNotFoundError(
        "Missing taxonomy lookup. Expected SQLite table taxonomy_resolved or a table under "
        "data_raw/taxonomy/manual_overrides, data_raw/taxonomy/worms, or data_raw/taxonomy/gbif_backbone."
    )


def load_environment_table(project_root: str | Path) -> pd.DataFrame:
    """Load flattened environmental monthly data from SQLite or CMEMS tables."""

    project_root = Path(project_root)
    from_db = _read_sqlite_table(project_root, "environment_monthly")
    if from_db is not None:
        return from_db
    return _read_first_table(
        project_root / "data_raw" / "cmems" / "monthly_tables",
        "environment table or SQLite table environment_monthly",
    )


def load_validation_table(project_root: str | Path) -> pd.DataFrame:
    """Load manual validation labels from SQLite or validation files."""

    project_root = Path(project_root)
    from_db = _read_sqlite_table(project_root, "validation")
    if from_db is not None:
        return from_db
    return _read_first_table(
        project_root / "data_raw" / "validation",
        "validation table or SQLite table validation",
    )


def discover_full_run_inputs(project_root: str | Path) -> pd.DataFrame:
    """Return the first available input source for each full-rerun table."""

    project_root = Path(project_root)
    rows = []
    specs = [
        ("candidate_records", "candidate_records", project_root / "data_raw" / "extraction" / "jsonl"),
        ("taxonomy_resolved", "taxonomy_resolved", project_root / "data_raw" / "taxonomy"),
        ("environment_monthly", "environment_monthly", project_root / "data_raw" / "cmems" / "monthly_tables"),
        ("validation", "validation", project_root / "data_raw" / "validation"),
    ]
    for label, sqlite_table, folder in specs:
        db_source = None
        for db_path in _sqlite_files(project_root):
            if _table_exists(db_path, sqlite_table):
                db_source = db_path
                break
        files = _candidate_files(folder, TABLE_SUFFIXES)
        source = db_source if db_source is not None else files[0] if files else None
        rows.append(
            {
                "input_name": label,
                "sqlite_table": sqlite_table,
                "source": str(source) if source is not None else "",
                "status": "found" if source is not None else "missing",
            }
        )
    return pd.DataFrame(rows)


def require_full_run_inputs(project_root: str | Path) -> pd.DataFrame:
    """Return discovery table or raise a grouped missing-input error."""

    discovery = discover_full_run_inputs(project_root)
    missing = discovery[discovery["status"].eq("missing")]
    if not missing.empty:
        lines = [
            f"- {row.input_name}: SQLite table {row.sqlite_table} or a matching table file in data_raw"
            for row in missing.itertuples(index=False)
        ]
        raise FileNotFoundError("Missing full local rerun inputs:\n" + "\n".join(lines))
    return discovery


def run_full_local(project_root: str | Path, output_dir: str | Path) -> dict[str, Path]:
    """Run the full local workflow using user-supplied files or SQLite tables."""

    project_root = Path(project_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    discovery = require_full_run_inputs(project_root)

    candidates = load_candidate_records(project_root)
    taxonomy = load_taxonomy_lookup(project_root)
    environment = load_environment_table(project_root)
    validation = load_validation_table(project_root)

    duplicate_qc = compare_duplicate_runs(candidates)
    candidate_qc = classify_candidate_records(candidates)
    completeness = summarize_field_completeness(candidate_qc)
    harmonized = harmonize_records(candidate_qc)
    kept = harmonized[harmonized["record_keep"]].copy()
    coordinate_checked = flag_coordinate_quality(kept)
    coordinate_usable = coordinate_checked[coordinate_checked["coordinate_usable_for_environment"]].copy()
    with_taxonomy = attach_taxonomy(coordinate_usable, taxonomy)
    modelling = attach_nearest_environment(with_taxonomy, environment)

    env_cols = [
        "salinity",
        "temperature_c",
        "dissolved_oxygen",
        "chlorophyll_a",
        "mixed_layer_depth",
        "bio_chl",
        "bio_no3",
        "bio_po4",
        "bio_si",
        "bio_o2",
        "bio_fe",
        "bio_spco2",
        "bio_ph",
        "bio_phyc",
        "phy_so_mean",
        "phy_thetao_mean",
        "phy_mlotst_mean",
    ]
    env_cols = [col for col in env_cols if col in modelling.columns]

    outputs = {
        "input_discovery": output_dir / "00_input_discovery.csv",
        "duplicate_qc": output_dir / "01_duplicate_run_qc.csv",
        "candidate_qc": output_dir / "02_candidate_record_qc.csv",
        "field_completeness": output_dir / "03_field_completeness.csv",
        "harmonized_records": output_dir / "04_harmonized_records.csv",
        "coordinate_qc": output_dir / "05_coordinate_qc_no_point_modification.csv",
        "species_matched_records": output_dir / "06_species_matched_records.csv",
        "model_ready_records": output_dir / "07_environment_variable_matched_records.csv",
        "taxonomic_variance": output_dir / "08_taxonomic_variance_proxy.csv",
        "environment_correlation": output_dir / "09_environment_spearman_correlation.csv",
        "environment_models": output_dir / "10_environment_models.csv",
        "taxon_environment_models": output_dir / "11_taxon_environment_models.csv",
        "speciation_summary": output_dir / "12_speciation_summary.csv",
        "validation_metrics": output_dir / "13_validation_metrics.csv",
        "validation_error_classes": output_dir / "14_validation_error_classes.csv",
    }

    write_csv(discovery, outputs["input_discovery"])
    write_csv(duplicate_qc, outputs["duplicate_qc"])
    write_csv(candidate_qc, outputs["candidate_qc"])
    write_csv(completeness, outputs["field_completeness"])
    write_csv(harmonized, outputs["harmonized_records"])
    write_csv(coordinate_checked, outputs["coordinate_qc"])
    write_csv(with_taxonomy, outputs["species_matched_records"])
    write_csv(modelling, outputs["model_ready_records"])
    write_csv(summarize_taxonomic_variance(modelling), outputs["taxonomic_variance"])
    write_csv(spearman_environment_correlation(modelling, env_cols), outputs["environment_correlation"])
    write_csv(fit_environment_models(modelling, env_cols), outputs["environment_models"])
    write_csv(taxon_environment_response(modelling, env_cols, rank="phylum", min_records=10), outputs["taxon_environment_models"])
    write_csv(summarize_speciation(modelling), outputs["speciation_summary"])
    write_csv(validation_metrics(validation), outputs["validation_metrics"])
    write_csv(error_class_summary(validation), outputs["validation_error_classes"])
    return outputs
