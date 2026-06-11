"""Manual validation metrics and error summaries."""

from __future__ import annotations

import numpy as np
import pandas as pd


def validation_metrics(validation: pd.DataFrame, status_col: str = "validation_status") -> pd.DataFrame:
    """Calculate precision, recall, and F1 from validation labels."""

    status = validation[status_col].fillna("").str.lower()
    tp = int(status.eq("true_positive").sum())
    fp = int(status.eq("false_positive").sum())
    fn = int(status.eq("false_negative").sum())
    precision = tp / (tp + fp) if tp + fp else np.nan
    recall = tp / (tp + fn) if tp + fn else np.nan
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else np.nan
    return pd.DataFrame(
        [
            {
                "true_positive": tp,
                "false_positive": fp,
                "false_negative": fn,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "n_validated": int(len(validation)),
            }
        ]
    )


def error_class_summary(validation: pd.DataFrame) -> pd.DataFrame:
    """Summarize manual validation error classes."""

    if "error_class" not in validation:
        return pd.DataFrame(columns=["error_class", "n"])
    return (
        validation.assign(error_class=validation["error_class"].fillna("no_error"))
        .groupby("error_class", dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
    )
