"""Review-stage CSV workspace for post-extraction reconstruction."""

from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .env_match import haversine_km
from .geocoding import flag_coordinate_quality
from .harmonize import harmonize_records
from .io import read_table, write_csv
from .taxonomy import attach_taxonomy


DEFAULT_CONFIG = Path("config") / "review_stages.yaml"
TABLE_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls", ".jsonl", ".pkl", ".pickle"}


def load_review_config(project_root: str | Path, config_path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    """Load review-stage configuration."""

    root = Path(project_root)
    payload = yaml.safe_load((root / Path(config_path)).read_text(encoding="utf-8")) or {}
    config = payload.get("review_stages", payload)
    if not isinstance(config, dict):
        raise ValueError(f"Review-stage config must be a mapping: {config_path}")
    return config


def stage_dir(project_root: str | Path, config: dict[str, Any], stage_key: str) -> Path:
    root = Path(project_root)
    stage_dirs = config.get("stage_dirs", {})
    stage_name = stage_dirs.get(stage_key, stage_key)
    return root / config.get("root", "data/review_workspace") / stage_name


def stage_paths(project_root: str | Path, config: dict[str, Any], stage_key: str, filename: str) -> dict[str, Path]:
    base = stage_dir(project_root, config, stage_key)
    raw_dir = base / "raw_csv"
    manual_dir = base / "manual_corrected_csv"
    raw_dir.mkdir(parents=True, exist_ok=True)
    manual_dir.mkdir(parents=True, exist_ok=True)
    return {
        "stage_dir": base,
        "raw_dir": raw_dir,
        "manual_dir": manual_dir,
        "raw": raw_dir / filename,
        "manual": manual_dir / filename,
    }


def write_stage_table(
    project_root: str | Path,
    config: dict[str, Any],
    stage_key: str,
    filename: str,
    table: pd.DataFrame,
) -> dict[str, Path]:
    """Write raw CSV and initialize manual-corrected CSV if it is missing."""

    paths = stage_paths(project_root, config, stage_key, filename)
    write_csv(table, paths["raw"])
    if not paths["manual"].exists():
        shutil.copy2(paths["raw"], paths["manual"])
    return paths


def read_manual_stage_table(project_root: str | Path, config: dict[str, Any], stage_key: str, filename: str) -> pd.DataFrame:
    """Read the manual-corrected CSV for a stage."""

    paths = stage_paths(project_root, config, stage_key, filename)
    if not paths["manual"].exists():
        raise FileNotFoundError(f"Missing manual-corrected CSV for previous stage: {paths['manual']}")
    return read_table(paths["manual"])


def _article_doi_map(project_root: Path, config: dict[str, Any]) -> dict[str, str]:
    index_path = project_root / config.get("literature_index", "data/index/literature_index.csv")
    if not index_path.exists():
        return {}
    index = pd.read_csv(index_path, encoding="utf-8")
    if "source_id" not in index or "doi" not in index:
        return {}
    return dict(zip(index["source_id"].astype(str), index["doi"].astype(str)))


def aggregate_extraction_consensus(project_root: str | Path, config: dict[str, Any] | None = None) -> dict[str, Path]:
    """Collect per-article concentration-consensus CSVs into one review table."""

    root = Path(project_root)
    config = config or load_review_config(root)
    prompt_version = str(config.get("extraction_prompt_version", "v1"))
    doi_by_article = _article_doi_map(root, config)
    rows = []
    for article_dir in sorted((root / "data" / "articles").glob("*")):
        if not article_dir.is_dir():
            continue
        consensus_path = article_dir / "source" / prompt_version / "final" / "concentration_consensus_records.csv"
        if not consensus_path.exists():
            continue
        table = pd.read_csv(consensus_path, encoding="utf-8")
        if table.empty:
            continue
        table.insert(0, "article_folder", article_dir.name)
        table.insert(1, "original_doi", doi_by_article.get(article_dir.name, ""))
        table["source_consensus_csv"] = str(consensus_path.relative_to(root))
        rows.append(table)
    combined = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return write_stage_table(root, config, "extraction_aggregation", "extraction_consensus_aggregated.csv", combined)


def harmonize_measurements(project_root: str | Path, config: dict[str, Any] | None = None) -> dict[str, Path]:
    """Apply unit and wet-weight harmonization to manually reviewed extraction rows."""

    root = Path(project_root)
    config = config or load_review_config(root)
    records = read_manual_stage_table(root, config, "extraction_aggregation", "extraction_consensus_aggregated.csv")
    harmonized = harmonize_records(records)
    return write_stage_table(root, config, "measurement_harmonization", "measurement_harmonized.csv", harmonized)


def _table_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in TABLE_SUFFIXES)


def load_worms_lookup(project_root: str | Path, config: dict[str, Any]) -> pd.DataFrame:
    """Load the first WoRMS lookup table from the configured folder."""

    root = Path(project_root)
    folder = root / config.get("taxonomy", {}).get("worms_lookup_dir", "data/worms")
    files = _table_files(folder)
    if not files:
        raise FileNotFoundError(f"Missing WoRMS lookup table in: {folder}")
    return read_table(files[0])


def match_worms_taxonomy(project_root: str | Path, config: dict[str, Any] | None = None) -> dict[str, Path]:
    """Attach WoRMS-based taxonomy to manually reviewed harmonized records."""

    root = Path(project_root)
    config = config or load_review_config(root)
    records = read_manual_stage_table(root, config, "measurement_harmonization", "measurement_harmonized.csv")
    taxonomy = config.get("taxonomy", {})
    try:
        worms = load_worms_lookup(root, config)
        matched = attach_taxonomy(
            records,
            worms,
            scientific_cutoff=float(taxonomy.get("scientific_cutoff", 85)),
            common_cutoff=float(taxonomy.get("common_cutoff", 90)),
            genus_cutoff=float(taxonomy.get("genus_cutoff", 70)),
        )
        matched["worms_lookup_status"] = "matched_with_local_lookup"
    except FileNotFoundError as exc:
        matched = records.copy()
        matched["worms_lookup_status"] = f"missing_lookup: {exc}"
        matched["taxonomy_match_status"] = "not_run_missing_worms_lookup"
    return write_stage_table(root, config, "worms_taxonomy_matching", "worms_taxonomy_matched.csv", matched)


def prepare_geographic_review(project_root: str | Path, config: dict[str, Any] | None = None) -> dict[str, Path]:
    """Flag missing or non-ocean coordinates and prepare geocoding review columns."""

    root = Path(project_root)
    config = config or load_review_config(root)
    records = read_manual_stage_table(root, config, "worms_taxonomy_matching", "worms_taxonomy_matched.csv")
    geocoding = config.get("geocoding", {})
    ocean_shapefile = root / geocoding.get("ocean_shapefile", "data/geocoding/shp/ne_10m_ocean/ne_10m_ocean.shp")
    checked = flag_coordinate_quality(records, project_root=root, ocean_shapefile=ocean_shapefile)
    checked["geocoding_required"] = (
        checked["coordinate_status"].ne("usable_reported_coordinate")
        | checked["reported_coordinate_ocean_status"].eq("on_land_or_outside_ocean_polygon")
    )
    checked["geocoding_query"] = checked.apply(
        lambda row: ", ".join(
            str(row.get(col, "")).strip()
            for col in ["site_name", "region", "ocean"]
            if str(row.get(col, "")).strip() and not str(row.get(col, "")).startswith("No ")
        ),
        axis=1,
    )
    for column in ["geocoded_latitude", "geocoded_longitude", "geocoded_provider", "geocoding_notes"]:
        if column not in checked:
            checked[column] = ""
    checked["latitude_for_environment"] = checked["latitude"]
    checked["longitude_for_environment"] = checked["longitude"]
    geocoded_lat = pd.to_numeric(checked["geocoded_latitude"], errors="coerce")
    geocoded_lon = pd.to_numeric(checked["geocoded_longitude"], errors="coerce")
    use_geocoded = checked["geocoding_required"] & geocoded_lat.notna() & geocoded_lon.notna()
    checked.loc[use_geocoded, "geocoded_latitude"] = geocoded_lat[use_geocoded]
    checked.loc[use_geocoded, "geocoded_longitude"] = geocoded_lon[use_geocoded]
    checked.loc[use_geocoded, "latitude_for_environment"] = checked.loc[use_geocoded, "geocoded_latitude"]
    checked.loc[use_geocoded, "longitude_for_environment"] = checked.loc[use_geocoded, "geocoded_longitude"]
    return write_stage_table(root, config, "geographic_review", "geographic_review.csv", checked)


def _parse_year(value: object) -> int | None:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return None
    return int(number)


def _netcdf_candidates(folder: Path, keyword: str) -> list[Path]:
    if not folder.exists():
        return []
    keyword = keyword.lower()
    return sorted(path for path in folder.rglob("*.nc") if keyword in path.name.lower())


def _year_from_filename(path: Path) -> int | None:
    match = re.search(r"(19|20)\d{2}", path.name)
    return int(match.group(0)) if match else None


def select_netcdf_for_year(folder: Path, keyword: str, year: int | None, multi_year_filename: str) -> tuple[Path | None, str]:
    """Select nearest-year NetCDF, falling back to configured multi-year file."""

    candidates = _netcdf_candidates(folder, keyword)
    if year is not None:
        dated = [(path, _year_from_filename(path)) for path in candidates]
        dated = [(path, file_year) for path, file_year in dated if file_year is not None]
        if dated:
            path, file_year = min(dated, key=lambda item: abs(item[1] - year))
            return path, f"nearest_year_{file_year}"
    multi_year = folder / multi_year_filename
    if multi_year.exists():
        return multi_year, "multi_year_average"
    for path in candidates:
        if path.name.lower() == multi_year_filename.lower():
            return path, "multi_year_average"
    return None, "missing_netcdf"


def _nearest_netcdf_values(nc_path: Path, lat: float, lon: float) -> dict[str, object]:
    try:
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError("xarray is required for NetCDF extraction. Install xarray and netCDF4.") from exc

    with xr.open_dataset(nc_path) as dataset:
        lat_name = next((name for name in ["latitude", "lat", "nav_lat"] if name in dataset.coords or name in dataset), None)
        lon_name = next((name for name in ["longitude", "lon", "nav_lon"] if name in dataset.coords or name in dataset), None)
        if lat_name is None or lon_name is None:
            return {"netcdf_extract_status": "missing_lat_lon_coordinates"}
        selected = dataset.sel({lat_name: lat, lon_name: lon}, method="nearest")
        values: dict[str, object] = {}
        for name, variable in selected.data_vars.items():
            if variable.ndim == 0:
                value = variable.item()
                values[name] = value if not isinstance(value, bytes) else value.decode("utf-8", errors="replace")
        values["netcdf_extract_status"] = "ok"
        values["env_grid_latitude"] = float(selected[lat_name].values)
        values["env_grid_longitude"] = float(selected[lon_name].values)
        values["env_match_distance_km"] = haversine_km(lat, lon, values["env_grid_latitude"], values["env_grid_longitude"])
        return values


def attach_environment_from_netcdf(project_root: str | Path, config: dict[str, Any] | None = None) -> dict[str, Path]:
    """Attach physical and biogeochemical NetCDF values using reviewed coordinates."""

    root = Path(project_root)
    config = config or load_review_config(root)
    records = read_manual_stage_table(root, config, "geographic_review", "geographic_review.csv")
    netcdf = config.get("netcdf", {})
    cmems_root = root / netcdf.get("cmems_root", "data/cmems")
    multi_year_filename = netcdf.get("multi_year_filename", "Multi-year average.nc")
    physical_keyword = netcdf.get("physical_keyword", "physical")
    bio_keyword = netcdf.get("bio_keyword", "bio")

    rows = []
    for _, record in records.iterrows():
        row = record.to_dict()
        lat = pd.to_numeric(pd.Series([row.get("latitude_for_environment")]), errors="coerce").iloc[0]
        lon = pd.to_numeric(pd.Series([row.get("longitude_for_environment")]), errors="coerce").iloc[0]
        year = _parse_year(row.get("year"))
        if pd.isna(lat) or pd.isna(lon):
            row["environment_match_status"] = "missing_coordinate"
            rows.append(row)
            continue
        for label, keyword in [("physical", physical_keyword), ("bio", bio_keyword)]:
            nc_path, source_status = select_netcdf_for_year(cmems_root, keyword, year, multi_year_filename)
            row[f"{label}_netcdf_source"] = str(nc_path.relative_to(root)) if nc_path else ""
            row[f"{label}_netcdf_source_status"] = source_status
            if nc_path is None:
                continue
            try:
                values = _nearest_netcdf_values(nc_path, float(lat), float(lon))
            except Exception as exc:
                row[f"{label}_netcdf_extract_status"] = f"{type(exc).__name__}: {exc}"
                continue
            for key, value in values.items():
                row[f"{label}_{key}"] = value
        row["environment_match_status"] = "attempted"
        rows.append(row)
    matched = pd.DataFrame(rows)
    return write_stage_table(root, config, "environment_matching", "environment_matched.csv", matched)


def create_final_output(project_root: str | Path, config: dict[str, Any] | None = None) -> dict[str, Path]:
    """Copy manually reviewed environment-matched records into final output stage."""

    root = Path(project_root)
    config = config or load_review_config(root)
    records = read_manual_stage_table(root, config, "environment_matching", "environment_matched.csv")
    return write_stage_table(root, config, "final_output", "final_reconstructed_records.csv", records)


def run_review_stage(project_root: str | Path, stage: str, config_path: str | Path = DEFAULT_CONFIG) -> dict[str, Path]:
    """Run one named review stage."""

    root = Path(project_root)
    config = load_review_config(root, config_path)
    stages = {
        "extraction_aggregation": aggregate_extraction_consensus,
        "measurement_harmonization": harmonize_measurements,
        "worms_taxonomy_matching": match_worms_taxonomy,
        "geographic_review": prepare_geographic_review,
        "environment_matching": attach_environment_from_netcdf,
        "final_output": create_final_output,
    }
    if stage not in stages:
        raise ValueError(f"Unknown review stage: {stage}. Choose one of: {', '.join(stages)}")
    return stages[stage](root, config)


def run_review_workflow(project_root: str | Path, config_path: str | Path = DEFAULT_CONFIG) -> dict[str, dict[str, Path]]:
    """Run all review stages in order."""

    root = Path(project_root)
    config = load_review_config(root, config_path)
    ordered = [
        ("extraction_aggregation", aggregate_extraction_consensus),
        ("measurement_harmonization", harmonize_measurements),
        ("worms_taxonomy_matching", match_worms_taxonomy),
        ("geographic_review", prepare_geographic_review),
        ("environment_matching", attach_environment_from_netcdf),
        ("final_output", create_final_output),
    ]
    return {name: func(root, config) for name, func in ordered}
