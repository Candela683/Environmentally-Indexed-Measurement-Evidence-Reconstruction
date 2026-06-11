"""Quality-control helpers for schema-guided candidate extraction."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd


CORE_COMPARE_FIELDS = [
    "scientific_name",
    "tissue",
    "measurement_basis",
    "total_arsenic",
    "arsenic_unit",
    "arsenic_form",
    "site_name",
    "year",
    "month",
]


def compare_duplicate_runs(records: pd.DataFrame, fields: list[str] | None = None) -> pd.DataFrame:
    """Compare duplicate extraction runs for each record identifier."""

    if fields is None:
        fields = CORE_COMPARE_FIELDS
    available = [field for field in fields if field in records.columns]
    rows = []
    for record_id, group in records.groupby("record_id", dropna=False):
        runs = sorted(group["candidate_run"].dropna().astype(str).unique()) if "candidate_run" in group else []
        row = {
            "record_id": record_id,
            "n_candidate_rows": int(len(group)),
            "n_runs": int(len(runs)),
            "runs": "|".join(runs),
        }
        mismatches = []
        for field in available:
            values = group[field].dropna().astype(str).str.strip().str.lower().unique()
            if len(values) > 1:
                mismatches.append(field)
        row["duplicate_agreement"] = len(mismatches) == 0
        row["mismatch_fields"] = "|".join(mismatches)
        rows.append(row)
    return pd.DataFrame(rows)


def classify_candidate_records(records: pd.DataFrame) -> pd.DataFrame:
    """Add candidate-record QC flags before harmonization."""

    df = records.copy()
    reasons = []
    for _, row in df.iterrows():
        row_reasons = []
        if "source_support" in df and not bool(row.get("source_support")):
            row_reasons.append("unsupported_by_source")
        if "manual_keep" in df and not bool(row.get("manual_keep")):
            row_reasons.append("manual_exclusion")
        for field in ["scientific_name", "total_arsenic", "arsenic_unit", "measurement_basis"]:
            if field in df and pd.isna(row.get(field)):
                row_reasons.append(f"missing_{field}")
        reasons.append("|".join(row_reasons) if row_reasons else "pass_candidate_qc")
    df["candidate_qc_reason"] = reasons
    df["candidate_qc_pass"] = df["candidate_qc_reason"].eq("pass_candidate_qc")
    return df


def read_api_key(key_name: str, key_file: str | Path | None = None) -> str | None:
    """Read an API key from an environment variable or a local text file."""

    value = os.getenv(key_name)
    if value:
        return value.strip()
    if key_file is None:
        return None
    path = Path(key_file)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def build_api_config(base_url: str, key_name: str, key_file: str | Path | None = None, model: str | None = None) -> dict:
    """Build a provider config without embedding secrets in code."""

    key = read_api_key(key_name, key_file)
    return {
        "base_url": base_url,
        "api_key": key,
        "api_key_source": f"env:{key_name}" if os.getenv(key_name) else str(key_file) if key_file else None,
        "model": model,
        "ready": key is not None,
    }


def summarize_field_completeness(records: pd.DataFrame) -> pd.DataFrame:
    """Report field completeness for extraction and reconstruction audits."""

    rows = []
    n = len(records)
    for column in records.columns:
        present = int(records[column].notna().sum())
        rows.append(
            {
                "field": column,
                "n_present": present,
                "n_missing": int(n - present),
                "completeness": present / n if n else np.nan,
            }
        )
    return pd.DataFrame(rows)
