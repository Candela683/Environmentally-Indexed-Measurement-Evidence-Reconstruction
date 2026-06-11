from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arsenic_workflow.llm_config import load_dashscope_config, read_configured_api_key


def main() -> int:
    config = load_dashscope_config(project_root=ROOT)
    print(f"base_url={config.base_url}")
    print(f"api_key_env={config.api_key_env}")
    print(f"extraction_model={config.extraction_model}")
    print(f"extraction_enable_thinking={config.extraction_enable_thinking}")
    print(f"ocr_model={config.ocr_model}")
    print(f"qa_model={config.qa_model}")
    print(f"qa_enable_thinking={config.qa_enable_thinking}")
    print(f"qa_stream={config.qa_stream}")
    try:
        read_configured_api_key(config)
        print("api_key_status=found")
    except RuntimeError as exc:
        print(f"api_key_status=missing ({exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
