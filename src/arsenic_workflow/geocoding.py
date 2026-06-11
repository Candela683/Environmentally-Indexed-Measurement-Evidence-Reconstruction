"""Geographic quality checks that never modify user-provided coordinates."""

from __future__ import annotations

import numpy as np
import pandas as pd


def flag_coordinate_quality(records: pd.DataFrame) -> pd.DataFrame:
    """Add coordinate quality flags while preserving original coordinates."""

    df = records.copy()
    df["latitude_original"] = df.get("latitude", np.nan)
    df["longitude_original"] = df.get("longitude", np.nan)

    missing = df["latitude"].isna() | df["longitude"].isna()
    out_of_range = (
        df["latitude"].notna()
        & df["longitude"].notna()
        & ((df["latitude"].abs() > 90) | (df["longitude"].abs() > 180))
    )
    zero_zero = df["latitude"].eq(0) & df["longitude"].eq(0)

    df["coordinate_status"] = "usable_reported_coordinate"
    df.loc[missing, "coordinate_status"] = "missing_coordinate"
    df.loc[out_of_range, "coordinate_status"] = "invalid_coordinate_range"
    df.loc[zero_zero, "coordinate_status"] = "zero_zero_suspicious"
    df["coordinate_usable_for_environment"] = df["coordinate_status"].eq("usable_reported_coordinate")
    return df
