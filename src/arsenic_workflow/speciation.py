"""Arsenic speciation summaries used as chemical context."""

from __future__ import annotations

import numpy as np
import pandas as pd


SPECIATION_COLUMNS = {
    "as_iii_mg_per_kg_ww": "AsIII",
    "as_v_mg_per_kg_ww": "AsV",
    "arsenobetaine_mg_per_kg_ww": "AsB",
    "arsenosugars_mg_per_kg_ww": "Arsenosugars",
    "known_organic_as_mg_per_kg_ww": "KnownOrganicAs",
    "known_inorganic_as_mg_per_kg_ww": "KnownInorganicAs",
}


def summarize_speciation(records: pd.DataFrame) -> pd.DataFrame:
    """Summarize concentration and fraction patterns for available species."""

    rows = []
    total = records.get("arsenic_mg_per_kg_ww")
    for column, label in SPECIATION_COLUMNS.items():
        if column not in records:
            continue
        values = pd.to_numeric(records[column], errors="coerce")
        valid = values.dropna()
        rows.append(
            {
                "response_name": label,
                "kind": "concentration",
                "column": column,
                "n": int(valid.shape[0]),
                "median": float(valid.median()) if not valid.empty else np.nan,
                "mean": float(valid.mean()) if not valid.empty else np.nan,
                "p05": float(valid.quantile(0.05)) if not valid.empty else np.nan,
                "p95": float(valid.quantile(0.95)) if not valid.empty else np.nan,
            }
        )
        if total is None:
            continue
        fraction = values / pd.to_numeric(total, errors="coerce") * 100.0
        fraction = fraction.replace([np.inf, -np.inf], np.nan).dropna()
        rows.append(
            {
                "response_name": f"{label}_fraction",
                "kind": "fraction_percent",
                "column": column,
                "n": int(fraction.shape[0]),
                "median": float(fraction.median()) if not fraction.empty else np.nan,
                "mean": float(fraction.mean()) if not fraction.empty else np.nan,
                "p05": float(fraction.quantile(0.05)) if not fraction.empty else np.nan,
                "p95": float(fraction.quantile(0.95)) if not fraction.empty else np.nan,
            }
        )
    return pd.DataFrame(rows)
