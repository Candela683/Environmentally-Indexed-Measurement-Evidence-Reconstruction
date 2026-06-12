"""RIS-first literature indexing, PDF download, and screening workflow."""

from __future__ import annotations

import json
import re
import shutil
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from .llm_config import build_dashscope_client, load_dashscope_config


DEFAULT_RIS_PATH = Path("synthetic_bundle") / "data_raw" / "literature" / "ris" / "example.ris"
DEFAULT_INDEX_PATH = Path("synthetic_bundle") / "data_raw" / "literature" / "index" / "literature_index.csv"
DEFAULT_RAW_PDF_DIR = Path("synthetic_bundle") / "data_raw" / "literature" / "raw_pdfs"
DEFAULT_STANDARD_PDF_DIR = Path("synthetic_bundle") / "data_raw" / "literature" / "pdfs"
DEFAULT_SCREENING_PROMPT = Path("prompt") / "Screening_Prompt_Demo" / "Screening_Prompt_Demo.txt"
DEFAULT_SCREENING_OUTPUT_DIR = (
    Path("synthetic_bundle") / "data_raw" / "literature" / "screening" / "Screening_Prompt_Demo"
)
DEFAULT_DOWNLOAD_URL = (
    "https://papers.ssrn.com/sol3/Delivery.cfm/"
    "aa340b7a-b399-4314-9ba9-1b8dc99fa87a-MECA.pdf?abstractid=4476876&mirid=1"
)


@dataclass(frozen=True)
class RisRecord:
    """Normalized metadata from one RIS record."""

    source_id: str
    title: str
    authors: list[str]
    abstract: str
    doi: str
    url: str
    publisher: str
    notes: list[str]


def parse_ris_records(path: str | Path) -> list[dict[str, list[str]]]:
    """Parse RIS tags into raw tag dictionaries."""

    records: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line or len(line) < 6 or line[2:6] != "  - ":
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


def safe_ascii_slug(text: str, fallback: str = "untitled", max_length: int = 120) -> str:
    """Keep only English letters and digits; replace all other runs with underscores."""

    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return (slug[:max_length].strip("_") or fallback)


def source_id_from_doi(doi: str, fallback: str = "example") -> str:
    """Create a compact source id from DOI-like text."""

    match = re.search(r"ssrn\.(\d+)", doi, flags=re.IGNORECASE)
    if match:
        return f"ssrn_{match.group(1)}"
    return safe_ascii_slug(doi, fallback=fallback, max_length=60).lower()


def normalize_ris_record(raw: dict[str, list[str]]) -> RisRecord:
    """Normalize one raw RIS record."""

    title = (raw.get("T1") or raw.get("TI") or [""])[0]
    doi = (raw.get("DO") or [""])[0]
    return RisRecord(
        source_id=source_id_from_doi(doi, fallback=safe_ascii_slug(title, fallback="example").lower()),
        title=title,
        authors=raw.get("AU", []),
        abstract="\n".join(raw.get("AB", []) or raw.get("N2", [])),
        doi=doi,
        url=(raw.get("UR") or [""])[0],
        publisher=(raw.get("PB") or [""])[0],
        notes=raw.get("N1", []),
    )


def pdf_file_name(record: RisRecord) -> str:
    """Return prefix_suffix.pdf, where suffix is a title slug."""

    title_slug = safe_ascii_slug(record.title, fallback="untitled", max_length=120)
    return f"{record.source_id}_{title_slug}.pdf"


def illustrative_download_function(url: str, target_path: str | Path, timeout_seconds: int = 120) -> Path:
    """Illustrative download function for saving one PDF URL to a raw PDF path."""

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


def build_literature_index_rows(
    project_root: str | Path,
    ris_path: str | Path,
    pdf_url: str = DEFAULT_DOWNLOAD_URL,
) -> list[dict[str, object]]:
    """Read RIS records and convert them to literature-index rows."""

    root = Path(project_root)
    ris_file = root / Path(ris_path)
    rows = []
    for raw in parse_ris_records(ris_file):
        record = normalize_ris_record(raw)
        pdf_name = pdf_file_name(record)
        raw_pdf_path = root / DEFAULT_RAW_PDF_DIR / pdf_name
        rows.append(
            {
                "source_id": record.source_id,
                "ris_path": str(Path(ris_path)),
                "doi": record.doi,
                "title": record.title,
                "authors": "; ".join(record.authors),
                "abstract": record.abstract,
                "publication_url": record.url,
                "pdf_url": pdf_url,
                "raw_pdf_filename": pdf_name,
                "raw_pdf_path": str(raw_pdf_path.relative_to(root)),
                "pdf_downloaded": raw_pdf_path.exists(),
                "preliminary_screened": False,
                "screening_prompt_name": "",
                "screening_decision": "",
                "screening_reason": "",
                "screening_output_path": "",
                "standard_pdf_unit": "",
            }
        )
    return rows


def write_literature_index(project_root: str | Path, rows: list[dict[str, object]]) -> Path:
    """Write the small literature management CSV."""

    path = Path(project_root) / DEFAULT_INDEX_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")
    return path


def load_literature_index(project_root: str | Path) -> pd.DataFrame:
    """Load the literature management CSV."""

    return pd.read_csv(Path(project_root) / DEFAULT_INDEX_PATH)


def download_raw_pdfs(project_root: str | Path, index: pd.DataFrame, skip_existing: bool = True) -> pd.DataFrame:
    """Download each indexed PDF into the raw PDF folder."""

    root = Path(project_root)
    updated = index.copy()
    for row_index, row in updated.iterrows():
        target = root / str(row["raw_pdf_path"])
        if skip_existing and target.exists():
            updated.loc[row_index, "pdf_downloaded"] = True
            continue
        illustrative_download_function(str(row["pdf_url"]), target)
        updated.loc[row_index, "pdf_downloaded"] = target.exists()
    return updated


def build_screening_prompt(prompt_template: str, row: pd.Series, available_text: str = "") -> str:
    """Append publication metadata to the screening prompt template."""

    return (
        prompt_template.strip()
        + "\n\nPublication metadata:\n"
        + f"Title: {row.get('title', '')}\n"
        + f"Authors: {row.get('authors', '')}\n"
        + f"DOI: {row.get('doi', '')}\n"
        + f"Abstract: {row.get('abstract', '')}\n"
        + f"Available text: {available_text}\n"
    )


def parse_screening_json(text: str) -> dict[str, str]:
    """Parse Qwen screening output JSON."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    payload = json.loads(stripped)
    decision = str(payload.get("decision", "")).strip().upper()
    if decision not in {"YES", "NO", "UNCERTAIN"}:
        raise ValueError(f"Unexpected screening decision: {decision}")
    return {"decision": decision, "reason": str(payload.get("reason", "")).strip()}


def call_qwen_screening(project_root: str | Path, prompt: str) -> str:
    """Call Qwen for publication screening."""

    config = load_dashscope_config(project_root)
    client = build_dashscope_client(config)
    response = client.chat.completions.create(
        model=config.qa_model,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": config.qa_enable_thinking},
        stream=False,
    )
    return response.choices[0].message.content or ""


def create_standard_pdf_unit(project_root: str | Path, row: pd.Series) -> str:
    """Create the standard PDF unit only for screened YES records."""

    root = Path(project_root)
    source_pdf = root / str(row["raw_pdf_path"])
    unit_name = f"[yes]+{Path(str(row['raw_pdf_filename'])).stem}"
    pdf_dir = root / DEFAULT_STANDARD_PDF_DIR / unit_name / "pdf"
    metadata_dir = pdf_dir / "source_metadata"
    for folder in [
        pdf_dir,
        metadata_dir,
        pdf_dir / "extracted_text",
        pdf_dir / "extracted_tables",
        pdf_dir / "v1" / "prompt",
        pdf_dir / "v1" / "raw_response",
        pdf_dir / "v1" / "raw_json",
        pdf_dir / "v1" / "parsed_csv",
        pdf_dir / "v1" / "indexed_csv",
        pdf_dir / "v1" / "final",
    ]:
        folder.mkdir(parents=True, exist_ok=True)
    if source_pdf.exists():
        shutil.copy2(source_pdf, pdf_dir / "source.pdf")
    (pdf_dir / "doi.txt").write_text(str(row["doi"]) + "\n", encoding="utf-8")
    metadata = {
        "source_id": row["source_id"],
        "title": row["title"],
        "authors": row["authors"],
        "abstract": row.get("abstract", ""),
        "doi": row["doi"],
        "publication_url": row.get("publication_url", ""),
        "raw_pdf_path": row["raw_pdf_path"],
    }
    (metadata_dir / "ris_metadata.json").write_text(json.dumps(metadata, ensure_ascii=True, indent=2), encoding="utf-8")
    (metadata_dir / "source_id.txt").write_text(str(row["source_id"]) + "\n", encoding="utf-8")
    return str((DEFAULT_STANDARD_PDF_DIR / unit_name).as_posix())


def run_screening(project_root: str | Path, index: pd.DataFrame, prompt_path: str | Path) -> pd.DataFrame:
    """Screen indexed publications with Qwen and update the literature index."""

    root = Path(project_root)
    prompt_file = root / Path(prompt_path)
    prompt_template = prompt_file.read_text(encoding="utf-8")
    output_dir = root / DEFAULT_SCREENING_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    updated = index.copy()
    for row_index, row in updated.iterrows():
        prompt = build_screening_prompt(prompt_template, row)
        raw_response = call_qwen_screening(root, prompt)
        parsed = parse_screening_json(raw_response)
        output_path = output_dir / f"{Path(str(row['raw_pdf_filename'])).stem}_screening.json"
        output_path.write_text(
            json.dumps({"raw_response": raw_response, **parsed}, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        updated.loc[row_index, "preliminary_screened"] = True
        updated.loc[row_index, "screening_prompt_name"] = "Screening_Prompt_Demo"
        updated.loc[row_index, "screening_decision"] = parsed["decision"]
        updated.loc[row_index, "screening_reason"] = parsed["reason"]
        updated.loc[row_index, "screening_output_path"] = str(output_path.relative_to(root))
        if parsed["decision"] == "YES":
            updated.loc[row_index, "standard_pdf_unit"] = create_standard_pdf_unit(root, updated.loc[row_index])
    return updated


def initialize_literature_index_from_ris(
    project_root: str | Path,
    ris_path: str | Path = DEFAULT_RIS_PATH,
    pdf_url: str = DEFAULT_DOWNLOAD_URL,
) -> Path:
    """Create the literature management CSV from RIS metadata."""

    rows = build_literature_index_rows(project_root, ris_path, pdf_url=pdf_url)
    return write_literature_index(project_root, rows)
