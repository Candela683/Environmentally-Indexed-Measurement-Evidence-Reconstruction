"""Spatial and temporal matching to environmental covariates.

This module does not move, snap, correct, or overwrite geocoded sample points.
It only attaches values from the nearest environmental grid cell and records
the match distance. Coordinate correction belongs in manual geocoding review,
not in environmental matching.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points."""

    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def attach_nearest_environment(
    records: pd.DataFrame,
    environment: pd.DataFrame,
    env_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Attach nearest environmental row while preserving original coordinates."""

    if env_columns is None:
        env_columns = [c for c in environment.columns if c not in {"env_latitude", "env_longitude", "year", "month"}]

    rows = []
    env = environment.copy()
    for _, record in records.iterrows():
        candidates = env
        if not np.isnan(record.get("year", np.nan)) and "year" in env:
            same_year = candidates[candidates["year"] == int(record["year"])]
            if not same_year.empty:
                candidates = same_year
        if not np.isnan(record.get("month", np.nan)) and "month" in env:
            same_month = candidates[candidates["month"] == int(record["month"])]
            if not same_month.empty:
                candidates = same_month
        if candidates.empty or np.isnan(record.get("latitude", np.nan)) or np.isnan(record.get("longitude", np.nan)):
            rows.append({**record.to_dict(), "env_match_distance_km": np.nan})
            continue
        distances = candidates.apply(
            lambda row: haversine_km(record["latitude"], record["longitude"], row["env_latitude"], row["env_longitude"]),
            axis=1,
        )
        nearest = candidates.loc[distances.idxmin()]
        attached = record.to_dict()
        attached["sample_latitude_used_for_env"] = record["latitude"]
        attached["sample_longitude_used_for_env"] = record["longitude"]
        attached.update({col: nearest[col] for col in env_columns if col in nearest})
        attached["env_grid_latitude"] = nearest["env_latitude"]
        attached["env_grid_longitude"] = nearest["env_longitude"]
        attached["env_match_distance_km"] = float(distances.min())
        rows.append(attached)
    return pd.DataFrame(rows)
