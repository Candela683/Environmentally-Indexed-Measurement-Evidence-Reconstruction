"""Qwen/DashScope extraction helpers for screened literature PDFs."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import yaml

from .llm_config import build_dashscope_client, load_dashscope_config


TEMPLATE_RELATIVE_PATH = Path("config") / "prompts" / "extraction" / "prompt_v1.txt"
PROMPT_YAML_RELATIVE_PATH = Path("config") / "prompts" / "extraction" / "extraction_v1.yaml"

PROMPT_FIELDS = [
    "1-MarineOrganism",
    "2-Geo_Latitude",
    "3-Geo_Longitude",
    "4-Geo_CoordinateFormat",
    "5-Geo_SiteName",
    "6-Geo_Region",
    "7-Geo_Ocean",
    "8-Geo_HabitatType",
    "9-Time_Year",
    "10-Time_Month",
    "11-Time_Season",
    "12-Time_IsContinuous",
    "13-Method_Sampling",
    "14-Bio_CommonName",
    "15-Bio_ScientificName",
    "16-Bio_LifeStage",
    "17-Bio_Sex",
    "18-Env_Temperature",
    "19-Env_Salinity",
    "20-Env_DissolvedOxygen",
    "21-Env_pH",
    "22-Bio_Size",
    "23-Bio_Weight",
    "24-Bio_TissueType",
    "25-Method_Detection",
    "26-Method_MeasurementBasis",
    "27-Chem_WaterContent",
    "28-Chem_LipidContent",
    "29-Chem_TotalArsenic",
    "30-Chem_ArsenicSpecies",
    "31-Chem_InorganicArsenic",
    "32-Chem_OrganicArsenic",
    "33-Chem_AsIII",
    "34-Chem_AsV",
    "35-Chem_Arsenosugars",
    "36-Chem_Arsenobetaine",
    "37-Chem_ResidualArsenic",
    "38-Info_Notes",
    "39-Info_InfluenceFactors",
]


def _project_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def prompt_version_from_template(template_path: str | Path) -> str:
    """Return a compact version label such as v1 from prompt_v1.txt."""

    stem = Path(template_path).stem
    match = re.search(r"(v\d+)$", stem, flags=re.IGNORECASE)
    return match.group(1).lower() if match else stem.lower()


def load_extraction_prompt_spec(project_root: str | Path | None = None, prompt_yaml_path: str | Path | None = None) -> dict[str, object]:
    """Load extraction prompt metadata from YAML."""

    root = Path(project_root) if project_root is not None else _project_root_from_here()
    relative_path = Path(prompt_yaml_path) if prompt_yaml_path is not None else PROMPT_YAML_RELATIVE_PATH
    path = root / relative_path
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Extraction prompt YAML must be a mapping: {path}")
    version = str(payload.get("version", "")).strip()
    date = str(payload.get("date", "")).strip()
    prompt_file = str(payload.get("prompt_file", "")).strip()
    if not version or not date or not prompt_file:
        raise ValueError(f"Extraction prompt YAML requires version, date, and prompt_file: {path}")
    return {
        "version": version,
        "date": date,
        "prompt_file": Path("config") / "prompts" / "extraction" / prompt_file,
        "enable_thinking": bool(payload.get("enable_thinking", False)),
        "runs": int(payload.get("runs", 2)),
        "yaml_path": relative_path,
    }


def load_prompt_template(project_root: str | Path | None = None, template_relative_path: str | Path | None = None) -> str:
    """Load the original prompt template file."""

    root = Path(project_root) if project_root is not None else _project_root_from_here()
    relative_path = Path(template_relative_path) if template_relative_path is not None else TEMPLATE_RELATIVE_PATH
    path = root / relative_path
    if not path.exists():
        raise FileNotFoundError(f"Missing prompt template: {path}")
    return path.read_text(encoding="utf-8")


def build_extraction_prompt(
    article_text: str,
    project_root: str | Path | None = None,
    template_relative_path: str | Path | None = None,
) -> str:
    """Build the extraction prompt by filling the original template."""

    template = load_prompt_template(project_root, template_relative_path=template_relative_path)
    return template.replace("{Text}", article_text)


def call_qwen(
    prompt: str,
    model: str | None = None,
    project_root: str | Path | None = None,
    config_path: str | Path | None = None,
    enable_thinking: bool | None = None,
) -> str:
    """Call DashScope's OpenAI-compatible Qwen endpoint."""

    config = load_dashscope_config(project_root=project_root or _project_root_from_here(), config_path=config_path)
    client = build_dashscope_client(config)
    response = client.chat.completions.create(
        model=model or config.extraction_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=config.extraction_temperature,
        extra_body={"enable_thinking": config.extraction_enable_thinking if enable_thinking is None else enable_thinking},
    )
    return response.choices[0].message.content or ""


def extract_json_payload(text: str) -> object:
    """Extract the first JSON payload from a model response."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    starts = [idx for idx in [stripped.find("{"), stripped.find("[")] if idx >= 0]
    if not starts:
        raise ValueError("No JSON payload found in Qwen response.")
    start = min(starts)
    opener = stripped[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return json.loads(stripped[start : index + 1])
    raise ValueError("No complete JSON payload found in Qwen response.")


def _records_from_payload(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise ValueError("Qwen JSON payload must be an object or an array of objects.")
    if all(field in payload for field in PROMPT_FIELDS):
        return [payload]
    if "Data" in payload and "Fields" in payload:
        fields = payload["Fields"]
        return [dict(zip(fields, row)) for row in payload["Data"]]
    for key in ["records", "Records", "data", "Data"]:
        value = payload.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    raise ValueError("Qwen JSON payload does not contain recognizable extraction records.")


def _stat_mean(value: object) -> object:
    text = str(value)
    compact = text.replace(" ", "").upper()
    if not text or compact in {"NA", "NAN", "NONE", "NA-NA,NA+-NA", "NA-NA,NA+/-NA"} or text.startswith("No "):
        return ""
    match = re.search(r",\s*([-+]?\d*\.?\d+)\s*(?:\+-|\+/-)", text)
    if match:
        return match.group(1)
    numbers = re.findall(r"[-+]?\d*\.?\d+", text)
    return numbers[-1] if numbers else ""


def _stat_unit(value: object) -> str:
    text = str(value)
    parts = [part.strip() for part in text.split(",")]
    if len(parts) >= 3:
        return parts[-1]
    return ""


def _clean_basis(value: object) -> str:
    text = str(value).strip().lower()
    if text in {"ww", "wet weight"} or "wet" in text:
        return "wet weight"
    if text in {"dw", "dry weight"} or "dry" in text:
        return "dry weight"
    return str(value)


def _month_to_number(value: object) -> object:
    text = str(value).strip()
    month_map = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    if text.lower() in month_map:
        return month_map[text.lower()]
    return value


def qwen_json_to_candidate_records(
    payload: object,
    candidate_run: str = "QWEN",
    source_id: str = "UNKNOWN_SOURCE",
) -> pd.DataFrame:
    """Convert Qwen JSON to the candidate_records schema."""

    records = _records_from_payload(payload)
    rows = []
    for index, record in enumerate(records, start=1):
        rows.append(
            {
                "source_id": source_id,
                "candidate_run": candidate_run,
                "record_id": f"QWEN-R{index:03d}",
                "marine_organism": record.get("1-MarineOrganism", True),
                "site_name": record.get("5-Geo_SiteName"),
                "region": record.get("6-Geo_Region"),
                "ocean": record.get("7-Geo_Ocean"),
                "latitude": record.get("2-Geo_Latitude"),
                "longitude": record.get("3-Geo_Longitude"),
                "year": record.get("9-Time_Year"),
                "month": _month_to_number(record.get("10-Time_Month")),
                "scientific_name": record.get("15-Bio_ScientificName"),
                "common_name": record.get("14-Bio_CommonName"),
                "tissue": record.get("24-Bio_TissueType"),
                "measurement_basis": _clean_basis(record.get("26-Method_MeasurementBasis")),
                "water_content_percent": _stat_mean(record.get("27-Chem_WaterContent")),
                "total_arsenic": _stat_mean(record.get("29-Chem_TotalArsenic")),
                "arsenic_unit": _stat_unit(record.get("29-Chem_TotalArsenic")),
                "arsenic_form": record.get("30-Chem_ArsenicSpecies"),
                "as_iii_mg_per_kg_ww": _stat_mean(record.get("33-Chem_AsIII")),
                "as_v_mg_per_kg_ww": _stat_mean(record.get("34-Chem_AsV")),
                "arsenobetaine_mg_per_kg_ww": _stat_mean(record.get("36-Chem_Arsenobetaine")),
                "arsenosugars_mg_per_kg_ww": _stat_mean(record.get("35-Chem_Arsenosugars")),
                "source_support": True,
                "manual_keep": True,
                "notes": "qwen extraction",
            }
        )
    df = pd.DataFrame(rows)
    df["known_organic_as_mg_per_kg_ww"] = (
        pd.to_numeric(df["arsenobetaine_mg_per_kg_ww"], errors="coerce")
        + pd.to_numeric(df["arsenosugars_mg_per_kg_ww"], errors="coerce")
    )
    df["known_inorganic_as_mg_per_kg_ww"] = (
        pd.to_numeric(df["as_iii_mg_per_kg_ww"], errors="coerce")
        + pd.to_numeric(df["as_v_mg_per_kg_ww"], errors="coerce")
    )
    return df


def add_extraction_index(candidates: pd.DataFrame, prompt_version: str, run_number: int) -> pd.DataFrame:
    """Add stable row indexes for prompt-versioned extraction auditing."""

    df = candidates.copy()
    df.insert(0, "extraction_index", [f"{prompt_version}_run{run_number:02d}_row{idx:03d}" for idx in range(1, len(df) + 1)])
    df.insert(1, "prompt_version", prompt_version)
    df.insert(2, "prompt_run_number", run_number)
    return df


def save_qwen_artifacts(
    article_dir: str | Path,
    prompt_template_path: str | Path,
    prompt: str,
    response: str,
    payload: object,
    candidates: pd.DataFrame,
    run_number: int = 1,
    model: str = "qwen-plus-latest",
) -> dict[str, Path]:
    """Save prompt-versioned Qwen artifacts under the PDF folder."""

    article_dir = Path(article_dir)
    prompt_template_path = Path(prompt_template_path)
    prompt_version = prompt_version_from_template(prompt_template_path)
    version_dir = article_dir / "source" / prompt_version
    prompt_dir = version_dir / "prompt"
    response_dir = version_dir / "raw_response"
    json_dir = version_dir / "raw_json"
    parsed_dir = version_dir / "parsed_csv"
    indexed_dir = version_dir / "indexed_csv"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    response_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)
    parsed_dir.mkdir(parents=True, exist_ok=True)
    indexed_dir.mkdir(parents=True, exist_ok=True)
    indexed = add_extraction_index(candidates, prompt_version, run_number)
    run_label = f"run_{run_number:02d}"
    safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", model)
    paths = {
        "version_dir": version_dir,
        "prompt_template": prompt_dir / prompt_template_path.name,
        "filled_prompt": prompt_dir / f"{run_label}_filled_prompt.txt",
        "response": response_dir / f"{run_label}_{safe_model}_response.txt",
        "json": json_dir / f"{run_label}_raw.json",
        "parsed_csv": parsed_dir / f"{run_label}_parsed_records.csv",
        "indexed_csv": indexed_dir / f"{run_label}_indexed_records.csv",
    }
    template_source = _project_root_from_here() / prompt_template_path
    paths["prompt_template"].write_text(template_source.read_text(encoding="utf-8"), encoding="utf-8")
    paths["filled_prompt"].write_text(prompt, encoding="utf-8")
    paths["response"].write_text(response, encoding="utf-8")
    paths["json"].write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    candidates.to_csv(paths["parsed_csv"], index=False, encoding="utf-8")
    indexed.to_csv(paths["indexed_csv"], index=False, encoding="utf-8")
    return paths
