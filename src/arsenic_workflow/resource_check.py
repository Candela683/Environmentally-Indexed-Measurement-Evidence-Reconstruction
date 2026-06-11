"""Checks for local-only external resources used by full reruns."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RequiredResource:
    """A local file or folder expected by the full workflow."""

    relative_path: str
    description: str
    required_for_demo: bool = False


REQUIRED_EXTERNAL_RESOURCES = [
    RequiredResource("data_raw/literature/ris", "RIS or CSV bibliographic exports"),
    RequiredResource("data_raw/literature/pdfs", "legally obtained source PDFs"),
    RequiredResource("data_raw/literature/supplementary", "legally obtained supplementary files"),
    RequiredResource("data_raw/extraction/jsonl", "LLM extraction JSONL or CSV outputs"),
    RequiredResource("data_raw/extraction/parsed_tables", "locally parsed article tables"),
    RequiredResource("data_raw/taxonomy/gbif_backbone", "GBIF backbone taxonomy export"),
    RequiredResource("data_raw/taxonomy/worms", "WoRMS match or taxonomy export"),
    RequiredResource("data_raw/taxonomy/manual_overrides", "manual taxonomy corrections"),
    RequiredResource("data_raw/geocoding/cache", "local geocoding cache"),
    RequiredResource("data_raw/geocoding/manual_review", "manual locality review tables"),
    RequiredResource("data_raw/cmems/biogeochemistry", "CMEMS biogeochemistry monthly products"),
    RequiredResource("data_raw/cmems/physics", "CMEMS physical monthly products"),
    RequiredResource("data_raw/cmems/monthly_tables", "flattened monthly environmental tables"),
    RequiredResource("data_raw/databases/sqlite", "optional local SQLite databases"),
    RequiredResource("data_raw/validation", "manual validation tables"),
]


def _has_user_file(path: Path) -> bool:
    """Return True when a directory contains at least one non-placeholder file."""

    if path.is_file():
        return True
    if not path.is_dir():
        return False
    for item in path.rglob("*"):
        if item.is_file() and item.name != ".gitkeep" and item.suffix.lower() != ".md":
            return True
    return False


def check_external_resources(project_root: str | Path) -> list[str]:
    """Return human-readable missing-resource messages."""

    project_root = Path(project_root)
    missing = []
    for resource in REQUIRED_EXTERNAL_RESOURCES:
        path = project_root / resource.relative_path
        if not path.exists():
            missing.append(f"MISSING FOLDER: {resource.relative_path} - {resource.description}")
        elif not _has_user_file(path):
            missing.append(f"MISSING DATA: {resource.relative_path} - {resource.description}")
    return missing


def require_external_resources(project_root: str | Path) -> None:
    """Raise a clear error if full-rerun external resources are missing."""

    missing = check_external_resources(project_root)
    if missing:
        details = "\n".join(f"- {line}" for line in missing)
        raise FileNotFoundError(
            "External resources required for a full rerun are missing.\n"
            f"{details}\n"
            "The public demo does not need these resources. For full analysis, place the files in the paths above."
        )
