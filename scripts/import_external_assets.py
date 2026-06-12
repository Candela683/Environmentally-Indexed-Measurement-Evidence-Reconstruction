from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _safe_name(name: str) -> str:
    text = re.sub(r"^\[(?:yes|YES|Yes)\]\+?", "", name)
    text = re.sub(r"[^A-Za-z0-9._ -]+", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:120]


def _copy_file(source: Path, target: Path, manifest: list[dict[str, str]]) -> Path:
    if not source.exists():
        raise FileNotFoundError(f"Missing source file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    manifest.append(
        {
            "source": str(source),
            "target": str(target),
            "bytes": str(source.stat().st_size),
        }
    )
    return target


def _write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source", "target", "bytes"])
        writer.writeheader()
        writer.writerows(rows)


def copy_two_source_files(pdf_data: Path, root: Path, manifest: list[dict[str, str]]) -> list[Path]:
    source_files = []
    yes_dirs = [path for path in sorted(pdf_data.iterdir()) if path.is_dir() and path.name.startswith("[Yes]")]
    for index, folder in enumerate(yes_dirs[:2], start=1):
        pdf_files = sorted((folder / "pdf").glob("*.pdf"))
        if not pdf_files:
            continue
        unit_name = f"external_source_{index:02d}_{_safe_name(folder.name)}"
        source_dir = root / "data" / "articles" / unit_name / "source"
        copied_pdf = _copy_file(pdf_files[0], source_dir / f"{unit_name}.pdf", manifest)
        doi_log = folder / "pdf" / "doi.log"
        if doi_log.exists():
            _copy_file(doi_log, source_dir / "doi.txt", manifest)
        else:
            (source_dir / "doi.txt").write_text("not_available\n", encoding="utf-8")
        source_files.append(copied_pdf)
    return source_files


def copy_gbif(gbif_dir: Path, root: Path, manifest: list[dict[str, str]], full: bool = False) -> None:
    target_dir = root / "data" / "taxonomy" / "gbif_backbone"
    selected = [
        "unique_scientific_names.pkl",
        "unique_common_names.pkl",
    ]
    if full:
        selected.extend(
            [
                "taxon.db",
                "gbif_simple.db",
                "VernacularName.db",
                "sci_name_list.pkl",
                "common_name_list.pkl",
                "backbone.zip",
            ]
        )
    for name in selected:
        source = gbif_dir / name
        if source.exists():
            _copy_file(source, target_dir / name, manifest)
    (target_dir / "README.md").write_text(
        "GBIF resources copied from the local dependency folder. Large databases are copied only when --full-gbif is used.\n",
        encoding="utf-8",
    )


def copy_worms(worms_dir: Path, root: Path, manifest: list[dict[str, str]], full: bool = True) -> None:
    target_dir = root / "data" / "taxonomy" / "worms"
    selected = ["meta.xml", "eml.xml", "identifier.txt", "speciesprofile.txt"]
    if full:
        selected.append("taxon.txt")
    for name in selected:
        source = worms_dir / name
        if source.exists():
            _copy_file(source, target_dir / name, manifest)
    (target_dir / "README.md").write_text(
        "WoRMS resources copied from the local 2026-05-01 download folder.\n",
        encoding="utf-8",
    )


def copy_cmems(cmems_root: Path, root: Path, manifest: list[dict[str, str]], full: bool = False) -> None:
    target_dir = root / "data" / "cmems"
    small_files = [
        cmems_root / "phy" / "cmems_mod_glo_phy-all_my_0.25deg_P1M-m-allyear06.nc",
        cmems_root / "code" / "mannual_name_common.csv",
        cmems_root / "code" / "merged_name_df_manual.csv",
        cmems_root / "code" / "name_pairs_match_by_Sci.csv",
        cmems_root / "code" / "name_pairs_match_by_Com.csv",
    ]
    for source in small_files:
        if source.exists():
            rel = source.relative_to(cmems_root)
            _copy_file(source, target_dir / "netcdf_subset" / rel, manifest)

    inventory_rows = []
    for source in sorted(cmems_root.rglob("*")):
        if source.is_file():
            inventory_rows.append(
                {
                    "source": str(source),
                    "target": "",
                    "bytes": str(source.stat().st_size),
                }
            )
            if full:
                rel = source.relative_to(cmems_root)
                _copy_file(source, target_dir / "full_copy" / rel, manifest)
    _write_manifest(target_dir / "SOURCE_INVENTORY.csv", inventory_rows)
    (target_dir / "README.md").write_text(
        "CMEMS full files can be very large. Default import copies a small runnable subset and a source inventory. Use --full-cmems to copy all local CMEMS files.\n",
        encoding="utf-8",
    )


def copy_geocoding_shp(shp_root: Path, root: Path, manifest: list[dict[str, str]]) -> None:
    target_dir = root / "data" / "geocoding" / "shp"
    if not shp_root.exists():
        raise FileNotFoundError(f"Missing shapefile folder: {shp_root}")
    for source in sorted(shp_root.rglob("*")):
        if source.is_file():
            rel = source.relative_to(shp_root)
            _copy_file(source, target_dir / rel, manifest)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-data", default=r"D:\wuqiang\qiang\arsenic\pdf_data")
    parser.add_argument("--gbif", default=r"D:\wuqiang\qiang\arsenic\dependence_data\GBIF")
    parser.add_argument("--worms", default=r"D:\wuqiang\qiang\arsenic\WoRMS_download_2026-05-01")
    parser.add_argument("--cmems", default=r"D:\wuqiang\qiang\arsenic\database\CMEMS")
    parser.add_argument("--shp", default=r"D:\wuqiang\qiang\arsenic\database\shp")
    parser.add_argument("--full-gbif", action="store_true")
    parser.add_argument("--full-worms", action="store_true", default=True)
    parser.add_argument("--no-full-worms", action="store_false", dest="full_worms")
    parser.add_argument("--full-cmems", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    manifest: list[dict[str, str]] = []
    copied_pdfs = copy_two_source_files(Path(args.pdf_data), ROOT, manifest)
    copy_gbif(Path(args.gbif), ROOT, manifest, full=args.full_gbif)
    copy_worms(Path(args.worms), ROOT, manifest, full=args.full_worms)
    copy_cmems(Path(args.cmems), ROOT, manifest, full=args.full_cmems)
    copy_geocoding_shp(Path(args.shp), ROOT, manifest)
    _write_manifest(ROOT / "data" / "external_asset_manifest.csv", manifest)
    print(f"Copied PDF files: {len(copied_pdfs)}")
    print(f"Manifest: {ROOT / 'data' / 'external_asset_manifest.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
