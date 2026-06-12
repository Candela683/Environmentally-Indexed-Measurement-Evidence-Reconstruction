"""Record-level cleaning and arsenic concentration harmonization."""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import pandas as pd


MISSING_MARKERS = {
    "",
    "na",
    "nan",
    "none",
    "null",
    "not reported",
    "no",
    "no note",
    "no latitude",
    "no longitude",
}

UNIT_FACTORS_TO_MG_KG = {
    "mg/kg": 1.0,
    "mg kg-1": 1.0,
    "mg kg^-1": 1.0,
    "ug/g": 1.0,
    "microg/g": 1.0,
    "ug kg-1": 0.001,
    "ng/g": 0.001,
    "ug/kg": 0.001,
    "microg/kg": 0.001,
    "mg/g": 1000.0,
}

TISSUE_MAP = {
    "muscle": "Muscle",
    "flesh": "Muscle",
    "soft tissue": "Soft tissue",
    "whole body": "Whole body",
    "whole organism": "Whole body",
    "digestive gland": "Digestive gland",
    "hepatopancreas": "Digestive gland",
    "liver": "Liver",
    "gill": "Gill",
    "algae": "Algae/seaweed",
    "seaweed": "Algae/seaweed",
}


def clean_missing(value: Any) -> Any:
    """Convert common extraction placeholders to NaN."""

    if value is None:
        return np.nan
    if isinstance(value, float) and math.isnan(value):
        return np.nan
    text = str(value).strip()
    if text.lower() in MISSING_MARKERS:
        return np.nan
    return value


def parse_number(value: Any) -> float:
    """Parse a numeric value or a simple range, returning its midpoint."""

    value = clean_missing(value)
    if value is np.nan:
        return np.nan
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value)
    numbers = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)]
    if not numbers:
        return np.nan
    if len(numbers) >= 2 and re.search(r"\bto\b|-|~", text):
        return float(np.mean(numbers[:2]))
    return numbers[0]


def normalize_unit(unit: Any) -> str | float:
    """Normalize common arsenic concentration units."""

    unit = clean_missing(unit)
    if unit is np.nan:
        return np.nan
    text = str(unit).strip().lower()
    text = text.replace("micro", "u")
    text = text.replace("\u00b5", "u").replace("\u03bc", "u")
    text = text.replace(" dry weight", "").replace(" wet weight", "")
    text = text.replace("dw", "").replace("ww", "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("ug kg-1", "ug/kg").replace("ug g-1", "ug/g")
    text = text.replace("mg kg-1", "mg/kg")
    return text


def normalize_basis(value: Any) -> str | float:
    """Map measurement basis labels to wet, dry, or unknown."""

    value = clean_missing(value)
    if value is np.nan:
        return np.nan
    text = str(value).strip().lower()
    if "wet" in text or text in {"ww", "fresh weight", "fw"}:
        return "wet"
    if "dry" in text or text == "dw":
        return "dry"
    return "unknown"


def tissue_category(value: Any) -> str:
    """Collapse heterogeneous tissue labels to a small set."""

    value = clean_missing(value)
    if value is np.nan:
        return "Unspecified"
    text = str(value).strip().lower()
    for key, label in TISSUE_MAP.items():
        if key in text:
            return label
    return str(value).strip().title()


def convert_to_wet_weight(
    concentration: Any,
    unit: Any,
    basis: Any,
    water_content_percent: Any = np.nan,
    imputed_moisture_fraction: float = 0.75,
) -> tuple[float, str]:
    """Convert arsenic concentration to mg/kg wet weight."""

    raw = parse_number(concentration)
    unit_norm = normalize_unit(unit)
    basis_norm = normalize_basis(basis)
    if np.isnan(raw) or unit_norm not in UNIT_FACTORS_TO_MG_KG:
        return np.nan, "not_convertible"
    mg_kg = raw * UNIT_FACTORS_TO_MG_KG[unit_norm]
    if basis_norm == "wet":
        return mg_kg, "converted_wet"
    if basis_norm == "dry":
        water = parse_number(water_content_percent)
        moisture = water / 100.0 if not np.isnan(water) else imputed_moisture_fraction
        moisture = min(max(moisture, 0.0), 0.99)
        status = "converted_dry_observed_moisture" if not np.isnan(water) else "converted_dry_imputed_moisture"
        return mg_kg * (1.0 - moisture), status
    return np.nan, "unknown_basis"


def harmonize_records(records: pd.DataFrame, imputed_moisture_fraction: float = 0.75) -> pd.DataFrame:
    """Clean candidate records and add standardized modelling columns."""

    df = records.copy()
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(clean_missing)

    converted = df.apply(
        lambda row: convert_to_wet_weight(
            row.get("total_arsenic"),
            row.get("arsenic_unit"),
            row.get("measurement_basis"),
            row.get("water_content_percent"),
            imputed_moisture_fraction=imputed_moisture_fraction,
        ),
        axis=1,
    )
    df["arsenic_mg_per_kg_ww"] = [item[0] for item in converted]
    df["unit_status"] = [item[1] for item in converted]
    df["tissue_category"] = df.get("tissue", pd.Series(index=df.index, dtype=object)).map(tissue_category)

    for col in ["latitude", "longitude", "year", "month"]:
        if col in df:
            df[col] = df[col].map(parse_number)

    keep = pd.Series(True, index=df.index)
    if "manual_keep" in df:
        keep &= df["manual_keep"].fillna(True).astype(bool)
    if "source_support" in df:
        keep &= df["source_support"].fillna(False).astype(bool)
    keep &= df["arsenic_mg_per_kg_ww"].notna()
    df["record_keep"] = keep
    return df
