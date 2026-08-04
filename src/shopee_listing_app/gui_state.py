from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import List

from .config_manager import load_app_config


@dataclass(frozen=True)
class GuiInitialState:
    stores: List[str]
    workbook_path: str
    ai_provider: str
    ai_default_model: str
    ai_fallback_models: List[str]
    ai_status_text: str


def build_initial_gui_state(config_dir: Path) -> GuiInitialState:
    config = load_app_config(config_dir)
    stores = [store.name for store in config.stores.values()]
    provider = config.ai.provider
    if provider.lower() == "offline":
        ai_status = "Offline placeholder mode is active; no AI API is used."
    elif provider.lower() == "zhipu":
        fallback = config.ai.fallback_models or ["glm-4.7", "glm-4.6", "glm-4.5-air"]
        ai_status = (
            f"AI API: Zhipu BigModel; primary model: {config.ai.model or 'glm-5.2'}; "
            f"fallback models: {' / '.join(fallback)}"
        )
    elif provider.lower() in {"openai", "multi_model", "multi-model", "nvidia", "nvidia_dual", "nvidia-dual"}:
        execution_mode = os.environ.get("AI_EXECUTION_MODE", "multimodal")
        selected_vision = (
            os.environ.get("STEP3_AI_MODEL")
            or os.environ.get("NVIDIA_VISION_MODEL")
            or "gpt-5.6"
        )
        step5_model = (
            os.environ.get("STEP5_AI_MODEL")
            or os.environ.get("STEP5_TEXT_MODEL")
            or "gpt-5.6"
        )
        step6_model = (
            os.environ.get("STEP6_AI_MODEL")
            or os.environ.get("STEP6_TEXT_MODEL")
            or "gpt-5.6"
        )
        step7_model = (
            os.environ.get("STEP7_AI_MODEL")
            or os.environ.get("STEP7_TEXT_MODEL")
            or "gpt-5.6"
        )
        execution_mode_label = (
            "multimodal"
            if execution_mode.strip().lower() == "multimodal"
            else "vision plus text"
        )
        ai_status = (
            f"AI execution mode: {execution_mode_label}; Step 3 model: {selected_vision}; "
            f"Step 5 model: {step5_model}; Step 6 model: {step6_model}; "
            f"Step 7 model: {step7_model}"
        )
    else:
        ai_status = f"AI API: {provider}"
    return GuiInitialState(
        stores=stores,
        workbook_path=config.workbook.path,
        ai_provider=provider,
        ai_default_model=config.ai.model,
        ai_fallback_models=config.ai.fallback_models,
        ai_status_text=ai_status,
    )
