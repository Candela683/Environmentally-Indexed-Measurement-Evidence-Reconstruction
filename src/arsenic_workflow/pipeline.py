"""End-to-end demonstration pipeline."""

from __future__ import annotations

from pathlib import Path

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


def run_demo(data_dir: str | Path, output_dir: str | Path) -> dict[str, Path]:
    """Run the public sample workflow and return output paths."""

    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = read_table(data_dir / "candidate_records_sample.csv")
    taxonomy = read_table(data_dir / "taxonomy_lookup_sample.csv")
    environment = read_table(data_dir / "environment_grid_sample.csv")
    validation = read_table(data_dir / "validation_sample.csv")

    duplicate_qc = compare_duplicate_runs(candidates)
    candidate_qc = classify_candidate_records(candidates)
    completeness = summarize_field_completeness(candidate_qc)
    harmonized = harmonize_records(candidate_qc)
    kept = harmonized[harmonized["record_keep"]].copy()
    coordinate_checked = flag_coordinate_quality(kept)
    coordinate_usable = coordinate_checked[coordinate_checked["coordinate_usable_for_environment"]].copy()
    with_taxonomy = attach_taxonomy(coordinate_usable, taxonomy)
    modelling = attach_nearest_environment(with_taxonomy, environment)

    env_cols = ["salinity", "temperature_c", "dissolved_oxygen", "chlorophyll_a", "mixed_layer_depth"]
    tax_summary = summarize_taxonomic_variance(modelling)
    env_corr = spearman_environment_correlation(modelling, env_cols)
    env_models = fit_environment_models(modelling, env_cols)
    taxon_env = taxon_environment_response(modelling, env_cols, rank="phylum", min_records=2)
    speciation = summarize_speciation(modelling)
    metrics = validation_metrics(validation)
    errors = error_class_summary(validation)

    outputs = {
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
    write_csv(duplicate_qc, outputs["duplicate_qc"])
    write_csv(candidate_qc, outputs["candidate_qc"])
    write_csv(completeness, outputs["field_completeness"])
    write_csv(harmonized, outputs["harmonized_records"])
    write_csv(coordinate_checked, outputs["coordinate_qc"])
    write_csv(with_taxonomy, outputs["species_matched_records"])
    write_csv(modelling, outputs["model_ready_records"])
    write_csv(tax_summary, outputs["taxonomic_variance"])
    write_csv(env_corr, outputs["environment_correlation"])
    write_csv(env_models, outputs["environment_models"])
    write_csv(taxon_env, outputs["taxon_environment_models"])
    write_csv(speciation, outputs["speciation_summary"])
    write_csv(metrics, outputs["validation_metrics"])
    write_csv(errors, outputs["validation_error_classes"])
    return outputs
