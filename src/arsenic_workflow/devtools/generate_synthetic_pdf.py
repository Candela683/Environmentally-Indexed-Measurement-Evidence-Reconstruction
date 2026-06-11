"""Generate a synthetic article PDF using only the Python standard library."""

from __future__ import annotations

from pathlib import Path


SYNTHETIC_RECORDS = [
    ["SYN001", "A", "SYN-R001", "Example Bay", "Example Coast", "Pacific", 36.05, 140.10, 2020, 7, "Mytilus edulis", "mussel", "soft tissue", "dry weight", 80, 18.4, "mg/kg", "total arsenic", 0.02, 0.08, 1.20, 0.30],
    ["SYN001", "B", "SYN-R001", "Example Bay", "Example Coast", "Pacific", 36.05, 140.10, 2020, 7, "Mytilus edulis", "mussel", "soft tissue", "dry weight", 80, 18.7, "mg/kg", "total arsenic", 0.02, 0.09, 1.25, 0.31],
    ["SYN001", "A", "SYN-R002", "Demo Reef", "Example Island", "Pacific", -18.20, 147.70, 2019, 3, "Sargassum fusiforme", "brown seaweed", "whole organism", "wet weight", "", 5.6, "ug/g", "total arsenic", 0.03, 0.20, 0.05, 1.80],
    ["SYN001", "A", "SYN-R003", "Sample Estuary", "Example Estuary", "Atlantic", 45.30, -62.10, 2021, 9, "Gadus morhua", "cod", "muscle", "wet weight", "", 0.72, "mg/kg", "total arsenic", 0.01, 0.02, 0.45, 0.01],
    ["SYN001", "A", "SYN-R004", "Training Lagoon", "Example Lagoon", "Indian", -33.70, 18.40, 2018, 2, "Crassostrea gigas", "oyster", "digestive gland", "dry weight", "", 22.0, "mg/kg", "total arsenic", 0.04, 0.12, 2.50, 0.80],
]

TABLE_COLUMNS = [
    "source_id",
    "candidate_run",
    "record_id",
    "site_name",
    "region",
    "ocean",
    "latitude",
    "longitude",
    "year",
    "month",
    "scientific_name",
    "common_name",
    "tissue",
    "measurement_basis",
    "water_content_percent",
    "total_arsenic",
    "arsenic_unit",
    "arsenic_form",
    "as_iii_mg_per_kg_ww",
    "as_v_mg_per_kg_ww",
    "arsenobetaine_mg_per_kg_ww",
    "arsenosugars_mg_per_kg_ww",
]


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _synthetic_lines() -> list[str]:
    lines = [
        "Synthetic Marine Arsenic Measurements In Example Organisms",
        "Abstract. This synthetic article was created only to test an evidence-to-model reconstruction workflow.",
        "It reports example arsenic measurements in marine organisms with locations, dates, tissues, units,",
        "weight basis, total arsenic, and selected arsenic species. Values are artificial.",
        "Methods. Samples were synthetically assigned to example coastal locations.",
        "Table 1. Synthetic record-level arsenic measurements",
        "BEGIN_SYNTHETIC_TABLE",
        ",".join(TABLE_COLUMNS),
    ]
    for record in SYNTHETIC_RECORDS:
        lines.append(",".join(str(value) for value in record))
    lines.extend(
        [
            "END_SYNTHETIC_TABLE",
            "Source note: all table entries are synthetic and generated for software testing.",
        ]
    )
    return lines


def _build_pdf(lines: list[str]) -> bytes:
    content_parts = ["BT", "/F1 8 Tf", "50 760 Td", "10 TL"]
    for line in lines:
        content_parts.append(f"({_pdf_escape(line)}) Tj")
        content_parts.append("T*")
    content_parts.append("ET")
    stream = "\n".join(content_parts).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(pdf)


def generate_synthetic_pdf(output_path: str | Path) -> Path:
    """Create the synthetic article PDF and return its path."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(_build_pdf(_synthetic_lines()))
    return output_path


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[3]
    generate_synthetic_pdf(
        root
        / "synthetic_bundle"
        / "data_raw"
        / "literature"
        / "pdfs"
        / "[yes]+synthetic_marine_arsenic_article"
        / "pdf"
        / "synthetic_arsenic_article.pdf"
    )
