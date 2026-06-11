"""DashScope OCR and streaming QA helpers driven by config files."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from .llm_config import DashScopeConfig, build_dashscope_client, load_dashscope_config


def image_to_data_url(path: str | Path) -> str:
    """Encode an image file as a data URL for OpenAI-compatible image input."""

    image_path = Path(path)
    mime_type, _ = mimetypes.guess_type(image_path.name)
    if mime_type is None:
        mime_type = "application/octet-stream"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def ocr_image(image_path: str | Path, config: DashScopeConfig | None = None) -> str:
    """Run OCR with the configured DashScope vision OCR model."""

    config = config or load_dashscope_config()
    client = build_dashscope_client(config)
    completion = client.chat.completions.create(
        model=config.ocr_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
                    {"type": "text", "text": config.ocr_image_prompt},
                ],
            },
        ],
    )
    return completion.choices[0].message.content or ""


def answer_question(text: str, config: DashScopeConfig | None = None, enable_thinking: bool | None = None) -> dict[str, Any]:
    """Answer text with the configured DashScope QA model."""

    config = config or load_dashscope_config()
    client = build_dashscope_client(config)
    prompt_template = config.qa_prompt_template.strip() or "{text}"
    prompt = prompt_template.replace("{text}", text) if "{text}" in prompt_template else f"{prompt_template}\n\n{text}"
    thinking = config.qa_enable_thinking if enable_thinking is None else enable_thinking
    completion = client.chat.completions.create(
        model=config.qa_model,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": thinking},
        stream=config.qa_stream,
    )
    if not config.qa_stream:
        return {"reasoning": "", "answer": completion.choices[0].message.content or "", "cancelled": False}

    answer_parts: list[str] = []
    reasoning_parts: list[str] = []
    for chunk in completion:
        choices = getattr(chunk, "choices", None)
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            continue
        reasoning_content = getattr(delta, "reasoning_content", None)
        if reasoning_content:
            reasoning_parts.append(reasoning_content)
        content = getattr(delta, "content", None)
        if content:
            answer_parts.append(content)
    return {"reasoning": "".join(reasoning_parts), "answer": "".join(answer_parts), "cancelled": False}
