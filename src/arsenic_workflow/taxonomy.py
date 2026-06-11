"""Taxonomic lookup helpers.

The release bundle uses a small CSV lookup table for demonstration. For the
full analysis, replace it with GBIF/WoRMS resolved names exported to the same
columns.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

import pandas as pd


TAXON_COLUMNS = [
    "scientific_name",
    "accepted_name",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
]


def _clean_name(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    text = re.sub(r"\s+", " ", text.strip())
    return text


def _name_key(value: object) -> str:
    text = _clean_name(value).lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _token_sort_score(left: str, right: str) -> float:
    left_key = " ".join(sorted(_name_key(left).split()))
    right_key = " ".join(sorted(_name_key(right).split()))
    if not left_key or not right_key:
        return 0.0
    try:
        from rapidfuzz import fuzz

        return float(fuzz.token_sort_ratio(left_key, right_key))
    except ImportError:
        return 100.0 * SequenceMatcher(None, left_key, right_key).ratio()


def _best_match(query: str, candidates: list[str]) -> tuple[str, float] | None:
    best_name = ""
    best_score = 0.0
    for candidate in candidates:
        score = _token_sort_score(query, candidate)
        if score > best_score:
            best_name = candidate
            best_score = score
    return (best_name, best_score) if best_name else None


def _candidate_id(row: pd.Series) -> object:
    for column in ["taxonID", "taxon_id", "gbifID", "gbif_id", "worms_id", "id"]:
        if column in row and pd.notna(row[column]):
            return row[column]
    return pd.NA


def _common_name_columns(taxonomy_lookup: pd.DataFrame) -> list[str]:
    return [column for column in ["common_name", "vernacular_name", "commonName"] if column in taxonomy_lookup.columns]


def _empty_match() -> dict[str, object]:
    return {
        "taxonomy_match_type": "none",
        "taxonomy_match_score": pd.NA,
        "taxonomy_matched_name": pd.NA,
        "taxonomy_matched_id": pd.NA,
        "taxonomy_matched_scientific_name": pd.NA,
        "taxonomy_match_status": "unmatched",
    }


def _match_one_taxon(
    scientific_name: object,
    common_name: object,
    taxonomy_lookup: pd.DataFrame,
    scientific_cutoff: float,
    common_cutoff: float,
    genus_cutoff: float,
) -> tuple[dict[str, object], pd.Series | None]:
    sci_query = _clean_name(scientific_name)
    common_query = _clean_name(common_name)
    lookup = taxonomy_lookup.copy()
    lookup["_scientific_key"] = lookup["scientific_name"].map(_name_key)

    if sci_query:
        exact = lookup[lookup["_scientific_key"].eq(_name_key(sci_query))]
        if not exact.empty:
            row = exact.iloc[0]
            return (
                {
                    "taxonomy_match_type": "scientific_exact",
                    "taxonomy_match_score": 100.0,
                    "taxonomy_matched_name": row["scientific_name"],
                    "taxonomy_matched_id": _candidate_id(row),
                    "taxonomy_matched_scientific_name": row["scientific_name"],
                    "taxonomy_match_status": "matched",
                },
                row,
            )

    sci_match = None
    sci_row = None
    if sci_query:
        sci_candidates = lookup["scientific_name"].dropna().astype(str).tolist()
        parts = _name_key(sci_query).split()
        if parts:
            genus = parts[0]
            genus_rows = lookup[lookup["genus"].map(_name_key).map(lambda value: _token_sort_score(genus, value) >= genus_cutoff)] if "genus" in lookup else lookup.iloc[0:0]
            if not genus_rows.empty:
                sci_candidates = genus_rows["scientific_name"].dropna().astype(str).tolist()
        sci_match = _best_match(sci_query, sci_candidates)
        if sci_match and sci_match[1] >= scientific_cutoff:
            sci_row = lookup[lookup["scientific_name"].astype(str).eq(sci_match[0])].iloc[0]

    common_match = None
    common_row = None
    common_columns = _common_name_columns(lookup)
    if common_query and common_columns:
        common_candidates = []
        common_to_index = {}
        for row_index, row in lookup.iterrows():
            for column in common_columns:
                value = _clean_name(row.get(column))
                if value:
                    common_candidates.append(value)
                    common_to_index[value] = row_index
        common_match = _best_match(common_query, common_candidates)
        if common_match and common_match[1] >= common_cutoff:
            common_row = lookup.loc[common_to_index[common_match[0]]]

    sci_score = sci_match[1] if sci_match else 0.0
    common_score = common_match[1] if common_match else 0.0
    if sci_row is not None and sci_score >= common_score:
        row = sci_row
        return (
            {
                "taxonomy_match_type": "scientific_fuzzy",
                "taxonomy_match_score": round(sci_score, 2),
                "taxonomy_matched_name": sci_match[0],
                "taxonomy_matched_id": _candidate_id(row),
                "taxonomy_matched_scientific_name": row["scientific_name"],
                "taxonomy_match_status": "matched",
            },
            row,
        )
    if common_row is not None:
        row = common_row
        return (
            {
                "taxonomy_match_type": "common_fuzzy",
                "taxonomy_match_score": round(common_score, 2),
                "taxonomy_matched_name": common_match[0],
                "taxonomy_matched_id": _candidate_id(row),
                "taxonomy_matched_scientific_name": row["scientific_name"],
                "taxonomy_match_status": "matched",
            },
            row,
        )
    return _empty_match(), None


def attach_taxonomy(
    records: pd.DataFrame,
    taxonomy_lookup: pd.DataFrame,
    scientific_cutoff: float = 85.0,
    common_cutoff: float = 90.0,
    genus_cutoff: float = 70.0,
) -> pd.DataFrame:
    """Attach accepted taxonomy using exact and genus-gated fuzzy name matching."""

    left = records.copy()
    right = taxonomy_lookup.copy()
    for column in TAXON_COLUMNS:
        if column not in right.columns:
            right[column] = pd.NA

    output_rows = []
    for _, record in left.iterrows():
        match_info, taxon_row = _match_one_taxon(
            record.get("scientific_name"),
            record.get("common_name"),
            right,
            scientific_cutoff=scientific_cutoff,
            common_cutoff=common_cutoff,
            genus_cutoff=genus_cutoff,
        )
        row = record.to_dict()
        row.update(match_info)
        for column in TAXON_COLUMNS[1:]:
            row[column] = taxon_row[column] if taxon_row is not None else pd.NA
        output_rows.append(row)
    return pd.DataFrame(output_rows)
