"""Geographic quality checks that never modify user-provided coordinates."""

from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd


OCEAN_SHAPEFILE_RELATIVE_PATH = (
    Path("data") / "geocoding" / "shp" / "ne_10m_ocean" / "ne_10m_ocean.shp"
)

RELOCATION_CANDIDATE_COORDINATES = [
    ("relocated_latitude", "relocated_longitude", "relocated_coordinate"),
    ("geocoded_latitude", "geocoded_longitude", "geocoded_coordinate"),
    ("candidate_latitude", "candidate_longitude", "candidate_coordinate"),
]


def _default_ocean_shapefile(project_root: str | Path | None = None) -> Path | None:
    """Return the first expected local ocean shapefile path that exists."""

    candidates = []
    if project_root is not None:
        root = Path(project_root)
        candidates.extend(
            [
                root / OCEAN_SHAPEFILE_RELATIVE_PATH,
            ]
        )
    candidates.append(Path.cwd() / OCEAN_SHAPEFILE_RELATIVE_PATH)
    for path in candidates:
        if path.exists():
            return path
    return None


def _ring_bounds(ring: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _point_in_bounds(lon: float, lat: float, bounds: tuple[float, float, float, float]) -> bool:
    min_x, min_y, max_x, max_y = bounds
    return min_x <= lon <= max_x and min_y <= lat <= max_y


def _point_in_ring(lon: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    """Return True when a lon/lat point is inside one polygon ring."""

    inside = False
    point_count = len(ring)
    if point_count < 3:
        return False
    previous_x, previous_y = ring[-1]
    for current_x, current_y in ring:
        crosses = (current_y > lat) != (previous_y > lat)
        if crosses:
            x_at_lat = (previous_x - current_x) * (lat - current_y) / (previous_y - current_y) + current_x
            if lon < x_at_lat:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


@lru_cache(maxsize=4)
def _load_polygon_rings(shapefile_path: str) -> list[tuple[tuple[float, float, float, float], list[tuple[float, float]], tuple[float, float, float, float]]]:
    """Load polygon rings from a .shp file using the shapefile binary format."""

    path = Path(shapefile_path)
    rings = []
    data = path.read_bytes()
    offset = 100
    while offset + 8 <= len(data):
        content_length_words = struct.unpack(">i", data[offset + 4 : offset + 8])[0]
        content_start = offset + 8
        content_end = content_start + content_length_words * 2
        if content_end > len(data) or content_start + 44 > len(data):
            break

        shape_type = struct.unpack("<i", data[content_start : content_start + 4])[0]
        if shape_type in {5, 15, 25, 31}:
            box = struct.unpack("<4d", data[content_start + 4 : content_start + 36])
            number_of_parts, number_of_points = struct.unpack("<2i", data[content_start + 36 : content_start + 44])
            parts_start = content_start + 44
            parts_end = parts_start + 4 * number_of_parts
            points_start = parts_end
            points_end = points_start + 16 * number_of_points
            if points_end <= content_end:
                parts = list(struct.unpack(f"<{number_of_parts}i", data[parts_start:parts_end]))
                points_raw = struct.unpack(f"<{number_of_points * 2}d", data[points_start:points_end])
                points = list(zip(points_raw[0::2], points_raw[1::2]))
                part_starts = parts + [number_of_points]
                for part_index in range(number_of_parts):
                    ring = points[part_starts[part_index] : part_starts[part_index + 1]]
                    if len(ring) >= 3:
                        rings.append((box, ring, _ring_bounds(ring)))
        offset = content_end
    return rings


def point_in_ocean(lon: float, lat: float, shapefile_path: str | Path) -> bool:
    """Check whether a WGS84 lon/lat point falls inside the ocean polygon."""

    inside = False
    for shape_bounds, ring, ring_bounds in _load_polygon_rings(str(Path(shapefile_path))):
        if not _point_in_bounds(lon, lat, shape_bounds):
            continue
        if _point_in_bounds(lon, lat, ring_bounds) and _point_in_ring(lon, lat, ring):
            inside = not inside
    return inside


def _coordinate_pair_status(lat: object, lon: object, ocean_shapefile: Path | None) -> tuple[object, str]:
    lat_num = pd.to_numeric(pd.Series([lat]), errors="coerce").iloc[0]
    lon_num = pd.to_numeric(pd.Series([lon]), errors="coerce").iloc[0]
    if pd.isna(lat_num) or pd.isna(lon_num):
        return pd.NA, "missing_coordinate"
    if abs(lat_num) > 90 or abs(lon_num) > 180:
        return pd.NA, "invalid_coordinate_range"
    if ocean_shapefile is None:
        return pd.NA, "ocean_shapefile_missing"
    in_ocean = point_in_ocean(float(lon_num), float(lat_num), ocean_shapefile)
    return in_ocean, "in_ocean" if in_ocean else "on_land_or_outside_ocean_polygon"


def add_ocean_position_flags(
    records: pd.DataFrame,
    project_root: str | Path | None = None,
    ocean_shapefile: str | Path | None = None,
) -> pd.DataFrame:
    """Add ocean-position flags for reported and candidate relocated coordinates."""

    df = records.copy()
    shapefile_path = Path(ocean_shapefile) if ocean_shapefile is not None else _default_ocean_shapefile(project_root)
    df["ocean_shapefile_used"] = str(shapefile_path) if shapefile_path is not None else ""

    reported = df.apply(
        lambda row: _coordinate_pair_status(row.get("latitude"), row.get("longitude"), shapefile_path),
        axis=1,
        result_type="expand",
    )
    df["reported_coordinate_in_ocean"] = reported[0]
    df["reported_coordinate_ocean_status"] = reported[1]
    df["reported_coordinate_ocean_checked"] = df["reported_coordinate_ocean_status"].isin(
        ["in_ocean", "on_land_or_outside_ocean_polygon"]
    )
    df["coordinate_needs_manual_geographic_review"] = (
        df["coordinate_status"].ne("usable_reported_coordinate")
        | df["reported_coordinate_ocean_status"].eq("on_land_or_outside_ocean_polygon")
    )

    has_reported_coordinate = df["latitude"].notna() & df["longitude"].notna()
    df["relocation_needed"] = ~has_reported_coordinate
    for lat_col, lon_col, prefix in RELOCATION_CANDIDATE_COORDINATES:
        if lat_col not in df.columns or lon_col not in df.columns:
            continue
        candidate = df.apply(
            lambda row: _coordinate_pair_status(row.get(lat_col), row.get(lon_col), shapefile_path),
            axis=1,
            result_type="expand",
        )
        df[f"{prefix}_in_ocean"] = candidate[0]
        df[f"{prefix}_ocean_status"] = candidate[1]
        df.loc[has_reported_coordinate, f"{prefix}_ocean_status"] = "not_used_reported_coordinate_present"
    return df


def flag_coordinate_quality(
    records: pd.DataFrame,
    project_root: str | Path | None = None,
    ocean_shapefile: str | Path | None = None,
) -> pd.DataFrame:
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
    return add_ocean_position_flags(df, project_root=project_root, ocean_shapefile=ocean_shapefile)
