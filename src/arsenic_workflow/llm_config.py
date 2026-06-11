"""Configuration helpers for OpenAI-compatible DashScope calls."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DASHSCOPE_CONFIG_RELATIVE_PATH = Path("config") / "dashscope_models.yaml"


@dataclass(frozen=True)
class DashScopeConfig:
    """Resolved DashScope provider and model settings."""

    base_url: str
    api_key_env: str
    api_key_file: Path | None
    extraction_model: str
    extraction_temperature: float
    extraction_enable_thinking: bool
    ocr_model: str
    ocr_image_prompt: str
    qa_model: str
    qa_enable_thinking: bool
    qa_stream: bool
    qa_prompt_template: str


def project_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def load_yaml_config(path: str | Path) -> dict[str, Any]:
    """Load a small YAML config file."""

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to read YAML configuration files.") from exc
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return data


def load_dashscope_config(project_root: str | Path | None = None, config_path: str | Path | None = None) -> DashScopeConfig:
    """Load DashScope settings from config/dashscope_models.yaml."""

    root = Path(project_root) if project_root is not None else project_root_from_here()
    path = Path(config_path) if config_path is not None else root / DASHSCOPE_CONFIG_RELATIVE_PATH
    data = load_yaml_config(path)
    dashscope = data.get("dashscope", {})
    if not isinstance(dashscope, dict):
        raise ValueError("Missing dashscope mapping in DashScope config.")

    extraction = dashscope.get("extraction", {}) or {}
    ocr = dashscope.get("ocr", {}) or {}
    qa = dashscope.get("qa", {}) or {}
    api_key_file_raw = dashscope.get("api_key_file")
    api_key_file = root / api_key_file_raw if api_key_file_raw else None
    return DashScopeConfig(
        base_url=str(dashscope.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")),
        api_key_env=str(dashscope.get("api_key_env", "DASHSCOPE_API_KEY")),
        api_key_file=api_key_file,
        extraction_model=str(extraction.get("model", "qwen-plus-latest")),
        extraction_temperature=float(extraction.get("temperature", 0)),
        extraction_enable_thinking=bool(extraction.get("enable_thinking", False)),
        ocr_model=str(ocr.get("model", "qwen-vl-ocr-2025-11-20")),
        ocr_image_prompt=str(ocr.get("image_prompt", "Extract only the visible text from this image.")),
        qa_model=str(qa.get("model", "qwen3.6-plus")),
        qa_enable_thinking=bool(qa.get("enable_thinking", False)),
        qa_stream=bool(qa.get("stream", True)),
        qa_prompt_template=str(qa.get("prompt_template", "{text}")),
    )


def read_configured_api_key(config: DashScopeConfig) -> str:
    """Read the configured API key without printing it."""

    value = os.getenv(config.api_key_env)
    if value:
        return value.strip()
    if config.api_key_file is not None and config.api_key_file.exists():
        file_value = config.api_key_file.read_text(encoding="utf-8").strip()
        if file_value:
            return file_value
    raise RuntimeError(
        f"Missing {config.api_key_env}. In PowerShell, inspect it with: echo $env:{config.api_key_env}"
    )


def build_dashscope_client(config: DashScopeConfig):
    """Build an OpenAI-compatible client using configured DashScope settings."""

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("The openai package is required in the active Python environment.") from exc
    return OpenAI(api_key=read_configured_api_key(config), base_url=config.base_url)
