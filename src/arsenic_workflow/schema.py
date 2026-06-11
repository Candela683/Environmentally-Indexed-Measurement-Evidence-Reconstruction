"""Column names and lightweight schema checks used by the workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


RAW_SCHEMA_FIELDS = [
    "source_id",
    "candidate_run",
    "record_id",
    "marine_organism",
    "site_name",
    "region",
    "ocean",
    "latitude",
    "longitude",
    "year",
    "month",
    "scientific_name",
    "common_name",
    "tissue",
    "measurement_basis",
    "water_content_percent",
    "total_arsenic",
    "arsenic_unit",
    "arsenic_form",
    "source_support",
    "manual_keep",
    "notes",
]

MODEL_FIELDS = [
    "source_id",
    "record_id",
    "scientific_name",
    "accepted_name",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
    "tissue_category",
    "arsenic_mg_per_kg_ww",
    "latitude",
    "longitude",
    "year",
    "month",
]


@dataclass(frozen=True)
class SchemaReport:
    """Result of a schema validation pass."""

    ok: bool
    missing: tuple[str, ...]
    extra: tuple[str, ...]


def check_columns(columns: Iterable[str], required: Iterable[str]) -> SchemaReport:
    """Compare an input table against a required field set."""

    observed = set(columns)
    required_set = set(required)
    missing = tuple(sorted(required_set - observed))
    extra = tuple(sorted(observed - required_set))
    return SchemaReport(ok=not missing, missing=missing, extra=extra)
