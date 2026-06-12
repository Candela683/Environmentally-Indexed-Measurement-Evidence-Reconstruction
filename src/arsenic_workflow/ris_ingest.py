"""RIS-first literature indexing, PDF download, and screening workflow."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import rispy
import yaml

from .llm_config import build_dashscope_client, load_dashscope_config


DEFAULT_RIS_PATH = Path("data") / "ris" / "example.ris"
DEFAULT_INDEX_PATH = Path("data") / "index" / "literature_index.csv"
DEFAULT_STANDARD_PDF_DIR = Path("data") / "articles"
DEFAULT_SCREENING_PROMPT = Path("config") / "prompts" / "abstract_screening" / "screening_v1.yaml"
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


def parse_ris_records(path: str | Path) -> list[dict[str, object]]:
    """Parse RIS records with rispy instead of line-by-line custom parsing."""

    with Path(path).open(encoding="utf-8") as handle:
        return list(rispy.load(handle))


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


def _first_value(value: object, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, list):
        return str(value[0]) if value else default
    return str(value)


def normalize_ris_record(raw: dict[str, object]) -> RisRecord:
    """Normalize one raw RIS record."""

    title = _first_value(raw.get("title") or raw.get("primary_title"))
    doi = _first_value(raw.get("doi"))
    urls = raw.get("urls") if isinstance(raw.get("urls"), list) else []
    source_id = _first_value(raw.get("id")) or source_id_from_doi(
        doi,
        fallback=safe_ascii_slug(title, fallback="example").lower(),
    )
    return RisRecord(
        source_id=source_id,
        title=title,
        authors=[str(author) for author in raw.get("authors", [])] if isinstance(raw.get("authors"), list) else [],
        abstract=_first_value(raw.get("abstract") or raw.get("notes_abstract")),
        doi=doi,
        url=_first_value(urls),
        publisher=_first_value(raw.get("publisher")),
        notes=[str(note) for note in raw.get("notes", [])] if isinstance(raw.get("notes"), list) else [],
    )


def source_url_from_ris_record(raw: dict[str, object], record: RisRecord, default_pdf_url: str = DEFAULT_DOWNLOAD_URL) -> str:
    """Return a direct source-file URL when the RIS record provides one."""

    for key in ["file_attachments1", "file_attachments2", "file_attachments", "link_to_pdf"]:
        value = _first_value(raw.get(key))
        if value:
            return value
    if "ssrn." in record.doi.lower():
        return default_pdf_url
    return ""


def source_file_name(record: RisRecord) -> str:
    """Return the stable source-id filename used after screening."""

    return f"{record.source_id}.pdf"


def article_unit_dir(source_id: str) -> Path:
    """Return the article-level data directory for one source id."""

    return DEFAULT_STANDARD_PDF_DIR / source_id


def article_source_dir(source_id: str) -> Path:
    """Return the source-file directory for one article."""

    return article_unit_dir(source_id) / "source"


def article_source_path(source_id: str) -> Path:
    """Return the expected source-file path for one article."""

    return article_source_dir(source_id) / f"{source_id}.pdf"


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
        record_pdf_url = source_url_from_ris_record(raw, record, default_pdf_url=pdf_url)
        filename = source_file_name(record)
        article_source = root / article_source_path(record.source_id)
        rows.append(
            {
                "source_id": record.source_id,
                "ris_path": str(Path(ris_path)),
                "doi": record.doi,
                "title": record.title,
                "authors": "; ".join(record.authors),
                "abstract": record.abstract,
                "publication_url": record.url,
                "pdf_url": record_pdf_url,
                "source_filename": filename,
                "source_file_path": str(article_source.relative_to(root)),
                "source_file_exists": article_source.exists(),
                "source_file_status": "existed" if article_source.exists() else "untried",
                "source_file_error": "",
                "preliminary_screened": False,
                "screening_prompt_name": "",
                "screening_decision": "",
                "screening_reason": "",
                "screening_output_path": "",
                "article_unit": "",
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


def normalize_article_source_file(project_root: str | Path, source_id: str) -> Path | None:
    """Move a manually supplied article file to source/<source_id>.pdf when found."""

    root = Path(project_root)
    article_dir = root / article_unit_dir(source_id)
    target = root / article_source_path(source_id)
    if target.exists():
        return target

    candidates = []
    for folder_name in ["source", "pdf"]:
        folder = article_dir / folder_name
        if folder.exists():
            candidates.extend(sorted(path for path in folder.glob("*.pdf") if path.is_file()))
    if not candidates:
        return None

    source = candidates[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        source.replace(target)
    return target


def download_article_source_files(
    project_root: str | Path,
    index: pd.DataFrame,
    skip_existing: bool = True,
    only_screened_yes: bool = True,
) -> pd.DataFrame:
    """Download or detect article source files after screening."""

    root = Path(project_root)
    updated = index.copy()
    for column, default in [
        ("source_file_status", "untried"),
        ("source_file_error", ""),
        ("source_file_exists", False),
    ]:
        if column not in updated:
            updated[column] = default
    for row_index, row in updated.iterrows():
        if only_screened_yes and str(row.get("screening_decision", "")).strip().upper() != "YES":
            continue
        source_id = str(row["source_id"])
        normalized = normalize_article_source_file(root, source_id)
        target = normalized or (root / str(row.get("source_file_path") or article_source_path(source_id)))
        updated.loc[row_index, "source_filename"] = target.name
        updated.loc[row_index, "source_file_path"] = str(target.relative_to(root))
        if target.exists():
            updated.loc[row_index, "source_file_exists"] = True
            updated.loc[row_index, "source_file_status"] = "existed"
            updated.loc[row_index, "source_file_error"] = ""
            continue
        previous_status = str(row.get("source_file_status", "")).strip().lower()
        if skip_existing and previous_status == "manual":
            updated.loc[row_index, "source_file_exists"] = False
            updated.loc[row_index, "source_file_status"] = "manual"
            continue
        updated.loc[row_index, "source_file_exists"] = False
        updated.loc[row_index, "source_file_status"] = "untried"
        updated.loc[row_index, "source_file_error"] = ""
        try:
            illustrative_download_function(str(row["pdf_url"]), target)
        except Exception as exc:
            updated.loc[row_index, "source_file_exists"] = False
            updated.loc[row_index, "source_file_status"] = "manual"
            updated.loc[row_index, "source_file_error"] = f"{type(exc).__name__}: {exc}"
            continue
        normalize_article_source_file(root, source_id)
        updated.loc[row_index, "source_file_exists"] = target.exists()
        updated.loc[row_index, "source_file_status"] = "existed" if target.exists() else "manual"
        updated.loc[row_index, "source_file_error"] = "" if target.exists() else "download finished but source file is missing"
    return updated


def build_screening_prompt(prompt_template: str, row: pd.Series, available_text: str = "") -> str:
    """Append publication metadata to the screening prompt template."""

    def text_value(name: str) -> str:
        value = row.get(name, "")
        if pd.isna(value):
            return ""
        return str(value)

    return (
        prompt_template.strip()
        + "\n\nPublication metadata:\n"
        + f"Title: {text_value('title')}\n"
        + f"Authors: {text_value('authors')}\n"
        + f"DOI: {text_value('doi')}\n"
        + f"Abstract: {text_value('abstract')}\n"
        + f"Available text: {available_text}\n"
    )


def load_screening_prompt(path: str | Path) -> dict[str, str]:
    """Load a versioned abstract-screening prompt YAML."""

    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Screening prompt YAML must be a mapping: {path}")
    version = str(payload.get("version", "")).strip()
    date = str(payload.get("date", "")).strip()
    prompt = str(payload.get("prompt", "")).strip()
    if not version or not date or not prompt:
        raise ValueError(f"Screening prompt YAML requires version, date, and prompt: {path}")
    return {
        "version": version,
        "date": date,
        "prompt": prompt,
        "enable_thinking": bool(payload.get("enable_thinking", False)),
    }


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


def call_qwen_screening(project_root: str | Path, prompt: str, enable_thinking: bool | None = None) -> str:
    """Call Qwen for publication screening."""

    config = load_dashscope_config(project_root)
    client = build_dashscope_client(config)
    thinking_enabled = config.qa_enable_thinking if enable_thinking is None else enable_thinking
    response = client.chat.completions.create(
        model=config.qa_model,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": thinking_enabled},
        stream=False,
    )
    return response.choices[0].message.content or ""


def create_article_source_unit(project_root: str | Path, row: pd.Series) -> str:
    """Create the article source-file unit only for screened YES records."""

    root = Path(project_root)
    unit_name = str(row["source_id"])
    source_dir = root / article_source_dir(unit_name)
    metadata_dir = source_dir / "source_metadata"
    for folder in [
        source_dir,
        metadata_dir,
        source_dir / "extracted_text",
        source_dir / "extracted_tables",
        source_dir / "v1" / "prompt",
        source_dir / "v1" / "raw_response",
        source_dir / "v1" / "raw_json",
        source_dir / "v1" / "parsed_csv",
        source_dir / "v1" / "indexed_csv",
        source_dir / "v1" / "final",
    ]:
        folder.mkdir(parents=True, exist_ok=True)
    (source_dir / "doi.txt").write_text(str(row["doi"]) + "\n", encoding="utf-8")
    metadata = {
        "source_id": row["source_id"],
        "title": row["title"],
        "authors": row["authors"],
        "abstract": row.get("abstract", ""),
        "doi": row["doi"],
        "publication_url": row.get("publication_url", ""),
        "source_file_path": row.get("source_file_path", ""),
    }
    (metadata_dir / "ris_metadata.json").write_text(json.dumps(metadata, ensure_ascii=True, indent=2), encoding="utf-8")
    (metadata_dir / "source_id.txt").write_text(str(row["source_id"]) + "\n", encoding="utf-8")
    return str((DEFAULT_STANDARD_PDF_DIR / unit_name).as_posix())


def remove_empty_source_unit(project_root: str | Path, source_id: str) -> None:
    """Remove a stale source subfolder when screening is not YES and no source file is present."""

    source_dir = Path(project_root) / article_source_dir(source_id)
    if not source_dir.exists():
        return
    if any(source_dir.rglob("*.pdf")):
        return
    for path in sorted(source_dir.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    source_dir.rmdir()


def run_screening(
    project_root: str | Path,
    index: pd.DataFrame,
    prompt_path: str | Path,
    enable_thinking: bool | None = None,
) -> pd.DataFrame:
    """Screen indexed publications with Qwen and update the literature index."""

    root = Path(project_root)
    prompt_file = root / Path(prompt_path)
    prompt_spec = load_screening_prompt(prompt_file)
    prompt_template = prompt_spec["prompt"]
    prompt_version = prompt_spec["version"]
    thinking_enabled = prompt_spec["enable_thinking"] if enable_thinking is None else enable_thinking
    updated = index.copy().fillna("")
    for row_index, row in updated.iterrows():
        prompt = build_screening_prompt(prompt_template, row)
        raw_response = call_qwen_screening(root, prompt, enable_thinking=thinking_enabled)
        parsed = parse_screening_json(raw_response)
        article_dir = root / article_unit_dir(str(row["source_id"]))
        output_dir = article_dir / "abstract_screening" / prompt_version
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "result.json"
        output_path.write_text(
            json.dumps(
                {
                    "prompt_version": prompt_version,
                    "prompt_date": prompt_spec["date"],
                    "enable_thinking": thinking_enabled,
                    "raw_response": raw_response,
                    **parsed,
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        updated.loc[row_index, "preliminary_screened"] = True
        updated.loc[row_index, "screening_prompt_name"] = prompt_version
        updated.loc[row_index, "screening_decision"] = parsed["decision"]
        updated.loc[row_index, "screening_reason"] = parsed["reason"]
        updated.loc[row_index, "screening_output_path"] = str(output_path.relative_to(root))
        if parsed["decision"] == "YES":
            updated.loc[row_index, "article_unit"] = create_article_source_unit(root, updated.loc[row_index])
        else:
            updated.loc[row_index, "article_unit"] = ""
            remove_empty_source_unit(root, str(row["source_id"]))
    return updated


def initialize_literature_index_from_ris(
    project_root: str | Path,
    ris_path: str | Path = DEFAULT_RIS_PATH,
    pdf_url: str = DEFAULT_DOWNLOAD_URL,
) -> Path:
    """Create the literature management CSV from RIS metadata."""

    rows = build_literature_index_rows(project_root, ris_path, pdf_url=pdf_url)
    return write_literature_index(project_root, rows)
