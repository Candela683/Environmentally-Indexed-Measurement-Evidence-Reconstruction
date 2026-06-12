"""RIS parsing and PDF-unit preparation helpers."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path


DEFAULT_RIS_PATH = Path("synthetic_bundle") / "data_raw" / "literature" / "ris" / "example.ris"
DEFAULT_PDF_ROOT = Path("synthetic_bundle") / "data_raw" / "literature" / "pdfs"
DEFAULT_DOWNLOAD_URL = (
    "https://papers.ssrn.com/sol3/Delivery.cfm/"
    "aa340b7a-b399-4314-9ba9-1b8dc99fa87a-MECA.pdf?abstractid=4476876&mirid=1"
)


@dataclass(frozen=True)
class RisRecord:
    """A small normalized subset of one RIS record."""

    title: str
    authors: list[str]
    doi: str
    url: str
    publisher: str
    notes: list[str]


def parse_ris_records(path: str | Path) -> list[dict[str, list[str]]]:
    """Parse RIS tags into a list of raw tag dictionaries."""

    records: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if len(line) < 6 or line[2:6] != "  - ":
            continue
        tag = line[:2]
        value = line[6:].strip()
        if tag == "TY":
            current = {"TY": [value]}
            continue
        if tag == "ER":
            if current:
                records.append(current)
            current = {}
            continue
        current.setdefault(tag, []).append(value)
    if current:
        records.append(current)
    return records


def normalize_ris_record(raw: dict[str, list[str]]) -> RisRecord:
    """Normalize one raw RIS record to fields used by the workflow."""

    return RisRecord(
        title=(raw.get("T1") or raw.get("TI") or [""])[0],
        authors=raw.get("AU", []),
        doi=(raw.get("DO") or [""])[0],
        url=(raw.get("UR") or [""])[0],
        publisher=(raw.get("PB") or [""])[0],
        notes=raw.get("N1", []),
    )


def slugify_title(title: str, fallback: str = "example") -> str:
    """Return a filesystem-safe, compact title slug."""

    text = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_").lower()
    return text[:80] or fallback


def create_pdf_unit_from_ris(
    project_root: str | Path,
    record: RisRecord,
    unit_name: str = "[yes]+example",
) -> dict[str, Path]:
    """Create the PDF-unit folder and write RIS-derived metadata."""

    root = Path(project_root)
    pdf_dir = root / DEFAULT_PDF_ROOT / unit_name / "pdf"
    metadata_dir = pdf_dir / "source_metadata"
    for folder in [
        pdf_dir,
        metadata_dir,
        pdf_dir / "extracted_text",
        pdf_dir / "extracted_tables",
    ]:
        folder.mkdir(parents=True, exist_ok=True)

    paths = {
        "pdf_dir": pdf_dir,
        "metadata_dir": metadata_dir,
        "doi": pdf_dir / "doi.txt",
        "metadata_json": metadata_dir / "ris_metadata.json",
        "source_id": metadata_dir / "source_id.txt",
        "source_pdf": pdf_dir / "source.pdf",
    }
    paths["doi"].write_text((record.doi or "not_available") + "\n", encoding="utf-8")
    paths["source_id"].write_text(slugify_title(record.title) + "\n", encoding="utf-8")
    paths["metadata_json"].write_text(json.dumps(asdict(record), ensure_ascii=True, indent=2), encoding="utf-8")
    return paths


def illustrative_download_function(url: str, target_path: str | Path, timeout_seconds: int = 120) -> Path:
    """Illustrative download function: download one PDF URL to a local target path."""

    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 literature-pdf-ingest-demo",
            "Accept": "application/pdf,application/octet-stream,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        target.write_bytes(response.read())
    return target


def prepare_pdf_unit_from_example_ris(
    project_root: str | Path,
    ris_path: str | Path | None = None,
    download_url: str = DEFAULT_DOWNLOAD_URL,
    unit_name: str = "[yes]+example",
    download_pdf: bool = True,
) -> dict[str, Path]:
    """Parse example.ris, extract DOI, create the PDF unit, and optionally download the PDF."""

    root = Path(project_root)
    ris_file = root / (Path(ris_path) if ris_path is not None else DEFAULT_RIS_PATH)
    raw_records = parse_ris_records(ris_file)
    if not raw_records:
        raise ValueError(f"No RIS records found in: {ris_file}")
    record = normalize_ris_record(raw_records[0])
    if not record.doi:
        raise ValueError(f"RIS record is missing DOI: {ris_file}")
    paths = create_pdf_unit_from_ris(root, record, unit_name=unit_name)
    paths["ris"] = ris_file
    if download_pdf:
        paths["downloaded_pdf"] = illustrative_download_function(download_url, paths["source_pdf"])
    return paths
