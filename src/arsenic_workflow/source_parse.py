"""Parse article source files into text and page images."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path


PAGE_MARKER_RE = re.compile(r"^=+\s*page_(?P<page>\d+)\s*=+$", re.IGNORECASE)
FIGURE_START_RE = re.compile(r"^(?P<label>fig(?:ure)?\.?\s*(?P<number>\d+[a-z]?)[\.)]?)\s+(?P<caption>.+)$", re.IGNORECASE)
SECTION_HEADING_RE = re.compile(
    r"^(?:(?P<number>\d+(?:\.\d+)*)(?:\.)?\s+)?(?P<title>"
    r"abstract|introduction|materials\s+(?:and|&)\s+methods?|methods?|methodology|"
    r"results?\s+(?:and|&)\s+discussion|results?|discussion|conclusions?|"
    r"acknowledge|acknowledgements?|acknowledgments?|references?|bibliography|supplementary(?:\s+materials?)?"
    r")\b[:.]?",
    re.IGNORECASE,
)

NOISE_LINE_RE = re.compile(
    r"^(?:\d+|preprint not peer reviewed|this preprint research paper has not been peer reviewed)$",
    re.IGNORECASE,
)

SECTION_ALIASES = [
    ("results_and_discussion", re.compile(r"^results?\s+(?:and|&)\s+discussion$", re.IGNORECASE)),
    ("abstract", re.compile(r"^abstract$", re.IGNORECASE)),
    ("introduction", re.compile(r"^introduction$", re.IGNORECASE)),
    ("methods", re.compile(r"^(materials\s+(?:and|&)\s+methods?|methods?|methodology)$", re.IGNORECASE)),
    ("results", re.compile(r"^results?$", re.IGNORECASE)),
    ("discussion", re.compile(r"^discussion$", re.IGNORECASE)),
    ("conclusion", re.compile(r"^conclusions?$", re.IGNORECASE)),
    ("acknowledgements", re.compile(r"^(acknowledge|acknowledgements?|acknowledgments?)$", re.IGNORECASE)),
    ("references", re.compile(r"^(references?|bibliography)$", re.IGNORECASE)),
    ("supplementary", re.compile(r"^supplementary(?:\s+materials?)?$", re.IGNORECASE)),
]

BROKEN_UNIT_MARKERS = ("�", "汛", "Î", "Â", "Ã")
UNIT_CONTEXT_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>(?:mg|ug|µg|μg|microg|ng|Î¼g|汛g|�g)[ \t]*(?:/[ \t]*(?:kg|g)|(?:kg|g)[ \t]*(?:-1|\^-1)))",
    re.IGNORECASE,
)
TEXT_PRIORITY_FILES = [
    ("full_text", "full_text.txt"),
    ("no_ref_text", "no_ref_text.txt"),
    ("ocrl_text", "ocrl_text.txt"),
    ("manual_text", "manual_text.txt"),
]


def _import_fitz():
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "Missing PyMuPDF. Install it with `pip install PyMuPDF` or add it to the active environment."
        ) from exc
    return fitz


def _project_root_from_article_dir(article_path: Path) -> Path:
    return article_path.parents[2]


def is_text_extraction_abnormal(text: str, min_visible_characters: int = 40) -> bool:
    """Return True when native PDF text looks too poor to trust."""

    if has_abnormal_concentration_units(text):
        return True
    clean = re.sub(r"\s+", "", text)
    if len(clean) < min_visible_characters:
        return True
    replacement_count = clean.count("\ufffd")
    if replacement_count and replacement_count / max(len(clean), 1) > 0.02:
        return True
    visible_count = sum(1 for char in clean if char.isprintable())
    if visible_count / max(len(clean), 1) < 0.85:
        return True
    return False


def has_abnormal_concentration_units(text: str) -> bool:
    """Detect concentration-unit snippets that look broken after PDF extraction."""

    from .harmonize import UNIT_FACTORS_TO_MG_KG, normalize_unit

    for match in UNIT_CONTEXT_RE.finditer(text):
        unit = match.group("unit").strip(" .,:;()[]")
        if not unit:
            continue
        if any(marker in unit for marker in BROKEN_UNIT_MARKERS):
            return True
        normalized = normalize_unit(unit)
        if isinstance(normalized, str) and normalized in UNIT_FACTORS_TO_MG_KG:
            continue
        if re.search(r"(?:g|kg)", unit, re.IGNORECASE) and any(token in unit.lower() for token in ["/", "kg", "g-1", "g^"]):
            return True
    return False


def ocr_page_image(image_path: str | Path, project_root: str | Path) -> str:
    """Run configured OCR for one rendered page image."""

    from .dashscope_vision_qa import ocr_image
    from .llm_config import load_dashscope_config

    config = load_dashscope_config(project_root=project_root)
    return ocr_image(image_path, config=config)


def iter_article_dirs(project_root: str | Path) -> list[Path]:
    """Return article folders under data/articles."""

    articles_dir = Path(project_root) / "data" / "articles"
    if not articles_dir.exists():
        return []
    return sorted(path for path in articles_dir.iterdir() if path.is_dir())


def expected_source_file(article_dir: str | Path) -> Path:
    """Return source/<article_id>.pdf for an article folder."""

    article_path = Path(article_dir)
    return article_path / "source" / f"{article_path.name}.pdf"


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _is_noise_line(line: str) -> bool:
    clean = _clean_line(line)
    return not clean or PAGE_MARKER_RE.match(clean) is not None or NOISE_LINE_RE.match(clean) is not None


def _normalize_section_title(title: str) -> str:
    clean = re.sub(r"\s+", " ", title.strip().lower())
    for section_name, pattern in SECTION_ALIASES:
        if pattern.match(clean):
            return section_name
    return "other"


def _looks_like_section_heading(line: str) -> tuple[str, str] | None:
    clean = _clean_line(line)
    match = SECTION_HEADING_RE.match(clean)
    if not match:
        return None
    if match.group("number") is None and not clean[:1].isupper():
        return None
    if match.group("number") is None and not clean.lower().startswith("abstract:") and len(clean.split()) > 8:
        return None
    title = match.group("title")
    return _normalize_section_title(title), clean


def _load_full_text_lines(article_path: Path) -> list[dict[str, object]]:
    full_text_path = article_path / "source" / "extracted_text" / "full_text.txt"
    if not full_text_path.exists():
        raise FileNotFoundError(f"Missing extracted full text: {full_text_path}")

    rows = []
    current_page = None
    for line_number, raw_line in enumerate(full_text_path.read_text(encoding="utf-8").splitlines(), start=1):
        clean = _clean_line(raw_line)
        marker = PAGE_MARKER_RE.match(clean)
        if marker:
            current_page = int(marker.group("page"))
        rows.append({"line_number": line_number, "page": current_page, "raw": raw_line, "clean": clean})
    return rows


def detect_major_sections(article_dir: str | Path) -> dict[str, object]:
    """Split extracted full text into common article sections."""

    article_path = Path(article_dir)
    rows = _load_full_text_lines(article_path)
    sections_dir = article_path / "source" / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in sections_dir.glob("*.txt"):
        stale_path.unlink()

    starts = []
    for row_index, row in enumerate(rows):
        clean = str(row["clean"])
        if _is_noise_line(clean):
            continue
        detected = _looks_like_section_heading(clean)
        if detected is None:
            continue
        section_name, heading = detected
        if section_name == "other":
            continue
        starts.append({"row_index": row_index, "section": section_name, "heading": heading})

    # Keep the first occurrence of each major section in reading order.
    deduped = []
    seen = set()
    for start in starts:
        section_name = str(start["section"])
        if section_name in seen:
            continue
        seen.add(section_name)
        deduped.append(start)

    manifest_sections = []
    for index, start in enumerate(deduped):
        start_index = int(start["row_index"])
        end_index = int(deduped[index + 1]["row_index"]) if index + 1 < len(deduped) else len(rows)
        section_rows = rows[start_index:end_index]
        lines = [str(row["clean"]) for row in section_rows if not _is_noise_line(str(row["clean"]))]
        section_text = "\n".join(lines).strip()
        section_name = str(start["section"])
        text_path = sections_dir / f"{section_name}.txt"
        text_path.write_text(section_text + ("\n" if section_text else ""), encoding="utf-8")
        manifest_sections.append(
            {
                "section": section_name,
                "heading": start["heading"],
                "start_line": rows[start_index]["line_number"],
                "end_line": rows[end_index - 1]["line_number"] if end_index > start_index else rows[start_index]["line_number"],
                "start_page": rows[start_index]["page"],
                "end_page": rows[end_index - 1]["page"] if end_index > start_index else rows[start_index]["page"],
                "text_path": str(text_path.relative_to(article_path)),
                "text_characters": len(section_text),
            }
        )

    manifest = {
        "article_id": article_path.name,
        "method": "regex_major_heading_detection",
        "sections": manifest_sections,
    }
    manifest_path = sections_dir / "sections_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")
    return manifest


def _caption_continuation_allowed(line: str) -> bool:
    clean = _clean_line(line)
    if _is_noise_line(clean):
        return False
    if _looks_like_section_heading(clean) is not None:
        return False
    if FIGURE_START_RE.match(clean):
        return False
    return True


def _nearest_page_image(article_path: Path, page_number: int | None) -> tuple[Path | None, int | None, str]:
    image_dir = article_path / "source" / "page_images"
    images = sorted(image_dir.glob("page_*.png"))
    if not images:
        return None, None, "missing_page_images"

    image_pages = []
    for image in images:
        match = re.search(r"page_(\d+)\.png$", image.name, re.IGNORECASE)
        if match:
            image_pages.append((int(match.group(1)), image))
    if not image_pages:
        return None, None, "missing_page_images"

    if page_number is None:
        image_page, image_path = image_pages[0]
        return image_path, image_page, "first_page_no_caption_page"

    image_page, image_path = min(image_pages, key=lambda item: abs(item[0] - page_number))
    method = "same_page" if image_page == page_number else "nearest_page"
    return image_path, image_page, method


def detect_figure_captions(article_dir: str | Path) -> dict[str, object]:
    """Detect Fig/Figure captions and connect them to the nearest rendered page image."""

    article_path = Path(article_dir)
    rows = _load_full_text_lines(article_path)
    figures_dir = article_path / "source" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in [figures_dir / "figure_manifest.json", figures_dir / "figure_manifest.csv"]:
        if stale_path.exists():
            stale_path.unlink()

    figures = []
    row_index = 0
    while row_index < len(rows):
        clean = str(rows[row_index]["clean"])
        match = FIGURE_START_RE.match(clean)
        if not match:
            row_index += 1
            continue

        caption_lines = [clean]
        next_index = row_index + 1
        while next_index < len(rows) and len(caption_lines) < 4:
            next_clean = str(rows[next_index]["clean"])
            if not _caption_continuation_allowed(next_clean):
                break
            if not next_clean.endswith(".") and len(next_clean) < 160:
                caption_lines.append(next_clean)
                next_index += 1
                continue
            caption_lines.append(next_clean)
            next_index += 1
            break

        caption = " ".join(caption_lines)
        figure_number = match.group("number").lower()
        figure_id = f"fig_{figure_number}"
        caption_page = rows[row_index]["page"]
        image_path, image_page, match_method = _nearest_page_image(article_path, caption_page if isinstance(caption_page, int) else None)
        figures.append(
            {
                "figure_id": figure_id,
                "figure_label": match.group("label").strip(),
                "caption": caption,
                "caption_line": rows[row_index]["line_number"],
                "caption_page": caption_page,
                "image_path": str(image_path.relative_to(article_path)) if image_path else "",
                "image_page": image_page,
                "match_method": match_method,
            }
        )
        row_index = max(row_index + 1, next_index)

    manifest = {
        "article_id": article_path.name,
        "method": "fig_caption_nearest_page_image",
        "figures": figures,
    }
    manifest_path = figures_dir / "figure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")

    csv_path = figures_dir / "figure_manifest.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "figure_id",
            "figure_label",
            "caption",
            "caption_line",
            "caption_page",
            "image_path",
            "image_page",
            "match_method",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(figures)
    return manifest


def analyze_article_structure(article_dir: str | Path) -> dict[str, object]:
    """Detect sections and figure links for an already parsed article."""

    article_path = Path(article_dir)
    sections = detect_major_sections(article_path)
    figures = detect_figure_captions(article_path)
    manifest = {
        "article_id": article_path.name,
        "sections_manifest": "source/sections/sections_manifest.json",
        "figure_manifest": "source/figures/figure_manifest.json",
        "figure_manifest_csv": "source/figures/figure_manifest.csv",
        "section_count": len(sections["sections"]),
        "figure_count": len(figures["figures"]),
    }
    manifest_path = article_path / "source" / "structure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")
    return manifest


def _remove_references_from_full_text(full_text: str) -> str:
    lines = full_text.splitlines()
    kept = []
    for line in lines:
        clean = _clean_line(line)
        detected = _looks_like_section_heading(clean)
        if detected is not None and detected[0] == "references":
            break
        kept.append(line)
    return "\n".join(kept).strip()


def build_text_priority_files(article_dir: str | Path, page_rows: list[dict[str, object]] | None = None) -> dict[str, object]:
    """Create full/no-reference/OCR/manual text layers and record the preferred one."""

    article_path = Path(article_dir)
    text_dir = article_path / "source" / "extracted_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    full_text_path = text_dir / "full_text.txt"
    if not full_text_path.exists():
        raise FileNotFoundError(f"Missing full text: {full_text_path}")

    full_text = full_text_path.read_text(encoding="utf-8")
    no_ref_path = text_dir / "no_ref_text.txt"
    no_ref_path.write_text(_remove_references_from_full_text(full_text) + "\n", encoding="utf-8")

    ocrl_path = text_dir / "ocrl_text.txt"
    ocr_pages = []
    if page_rows:
        for page in page_rows:
            if str(page.get("text_extraction_method", "")).startswith("ocr"):
                page_text_path = article_path / str(page.get("text_path", ""))
                if page_text_path.exists():
                    ocr_pages.append(f"\n\n===== page_{int(page['page']):03d} =====\n{page_text_path.read_text(encoding='utf-8').strip()}")
    ocrl_path.write_text("".join(ocr_pages).strip() + ("\n" if ocr_pages else ""), encoding="utf-8")

    manual_path = text_dir / "manual_text.txt"
    if not manual_path.exists():
        manual_path.write_text("", encoding="utf-8")

    entries = []
    selected = None
    for priority, (label, filename) in enumerate(TEXT_PRIORITY_FILES, start=1):
        path = text_dir / filename
        characters = len(path.read_text(encoding="utf-8").strip()) if path.exists() else 0
        entry = {
            "label": label,
            "priority": priority,
            "path": str(path.relative_to(article_path)),
            "characters": characters,
            "exists": path.exists(),
        }
        entries.append(entry)
        if characters > 0:
            selected = entry

    manifest = {
        "article_id": article_path.name,
        "priority_order": [item[0] for item in TEXT_PRIORITY_FILES],
        "selected_text": selected,
        "text_files": entries,
    }
    manifest_path = text_dir / "text_priority_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")
    return manifest


def parse_article_pdf(
    article_dir: str | Path,
    dpi: int = 180,
    overwrite: bool = True,
    ocr_on_abnormal: bool = True,
) -> dict[str, object]:
    """Extract text and page images from one article PDF."""

    fitz = _import_fitz()
    article_path = Path(article_dir)
    pdf_path = expected_source_file(article_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Missing source file: {pdf_path}")

    source_dir = article_path / "source"
    project_root = _project_root_from_article_dir(article_path)
    text_dir = source_dir / "extracted_text"
    image_dir = source_dir / "page_images"
    native_text_dir = text_dir / "native_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    native_text_dir.mkdir(parents=True, exist_ok=True)

    if overwrite:
        for folder, patterns in [
            (text_dir, ["page_*.txt", "full_text.txt"]),
            (native_text_dir, ["page_*.txt"]),
            (image_dir, ["page_*.png"]),
        ]:
            for pattern in patterns:
                for path in folder.glob(pattern):
                    path.unlink()

    page_rows = []
    full_text_parts = []
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(pdf_path) as document:
        for page_index, page in enumerate(document, start=1):
            page_label = f"page_{page_index:03d}"
            page_text = page.get_text("text").strip()
            text_path = text_dir / f"{page_label}.txt"
            native_text_path = native_text_dir / f"{page_label}.txt"
            image_path = image_dir / f"{page_label}.png"
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            pixmap.save(image_path)
            native_text_path.write_text(page_text + ("\n" if page_text else ""), encoding="utf-8")

            text_method = "native_pdf_text"
            ocr_error = ""
            if ocr_on_abnormal and is_text_extraction_abnormal(page_text):
                try:
                    ocr_text = ocr_page_image(image_path, project_root=project_root).strip()
                except Exception as exc:
                    ocr_text = ""
                    ocr_error = f"{type(exc).__name__}: {exc}"
                if ocr_text:
                    page_text = ocr_text
                    text_method = "ocr_fallback"
                elif ocr_error:
                    text_method = "native_pdf_text_ocr_failed"

            text_path.write_text(page_text + ("\n" if page_text else ""), encoding="utf-8")
            full_text_parts.append(f"\n\n===== {page_label} =====\n{page_text}")
            page_rows.append(
                {
                    "page": page_index,
                    "text_path": str(text_path.relative_to(article_path)),
                    "native_text_path": str(native_text_path.relative_to(article_path)),
                    "image_path": str(image_path.relative_to(article_path)),
                    "text_extraction_method": text_method,
                    "ocr_error": ocr_error,
                    "text_characters": len(page_text),
                    "image_bytes": image_path.stat().st_size,
                }
            )

    full_text_path = text_dir / "full_text.txt"
    full_text_path.write_text("".join(full_text_parts).strip() + "\n", encoding="utf-8")
    text_priority = build_text_priority_files(article_path, page_rows=page_rows)
    manifest = {
        "article_id": article_path.name,
        "source_file": str(pdf_path.relative_to(article_path)),
        "parser": "PyMuPDF",
        "dpi": dpi,
        "ocr_on_abnormal": ocr_on_abnormal,
        "page_count": len(page_rows),
        "full_text_path": str(full_text_path.relative_to(article_path)),
        "selected_text": text_priority["selected_text"],
        "text_priority_manifest": "source/extracted_text/text_priority_manifest.json",
        "pages": page_rows,
    }
    manifest.update(analyze_article_structure(article_path))
    manifest_path = source_dir / "parse_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")
    return manifest


def parse_all_article_pdfs(
    project_root: str | Path,
    dpi: int = 180,
    overwrite: bool = True,
    ocr_on_abnormal: bool = True,
) -> list[dict[str, object]]:
    """Parse every article source PDF found under data/articles."""

    results = []
    for article_dir in iter_article_dirs(project_root):
        pdf_path = expected_source_file(article_dir)
        if not pdf_path.exists():
            results.append(
                {
                    "article_id": article_dir.name,
                    "status": "missing_source_file",
                    "source_file": str(pdf_path),
                }
            )
            continue
        manifest = parse_article_pdf(article_dir, dpi=dpi, overwrite=overwrite, ocr_on_abnormal=ocr_on_abnormal)
        manifest["status"] = "parsed"
        results.append(manifest)
    return results
