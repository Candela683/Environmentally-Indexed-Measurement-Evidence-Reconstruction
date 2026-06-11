"""Small IO helpers with explicit UTF-8 defaults."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd


def read_table(path: str | Path) -> pd.DataFrame:
    """Read CSV, TSV, JSONL, Excel, or pickle tables by file suffix."""

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Missing input table: {path}. Please create this file or update the configured path.")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, encoding="utf-8-sig")
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t", encoding="utf-8-sig")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return pd.DataFrame(rows)
    if suffix in {".pkl", ".pickle"}:
        return pd.read_pickle(path)
    raise ValueError(f"Unsupported table suffix: {path.suffix}")


def write_csv(df: pd.DataFrame, path: str | Path) -> None:
    """Write a dataframe using a stable encoding."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def write_jsonl(rows: Iterable[dict], path: str | Path) -> None:
    """Write dictionaries as JSON Lines."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(text + "\n", encoding="utf-8")
