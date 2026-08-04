from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STORE_CONFIG_LOCK = threading.RLock()


@dataclass(frozen=True)
class StoreConfig:
    name: str
    status_column: str
    template_key: str
    listing_sheet: str = ""


@dataclass(frozen=True)
class WorkbookConfig:
    path: str
    sheet_prefix: str
    unlisted_status: str
    field_columns: Dict[str, str]


@dataclass(frozen=True)
class AIConfig:
    provider: str
    endpoint: str
    api_key_env: str
    model: str
    timeout_seconds: int
    fallback_models: List[str] = field(default_factory=list)
    max_retries_per_model: int = 2
    mask_api_key_in_logs: bool = True


@dataclass(frozen=True)
class AppConfig:
    config_dir: Path
    stores: Dict[str, StoreConfig]
    aliases: Dict[str, str]
    templates: Dict[str, str]
    workbook: WorkbookConfig
    ai: AIConfig

    def store(self, store_name: str) -> StoreConfig:
        key = normalize_key(store_name)
        if key in self.aliases:
            key = self.aliases[key]
        if key in self.stores:
            return self.stores[key]

        for known_key, store in self.stores.items():
            if key in known_key or known_key in key:
                return store
        known = ", ".join(store.name for store in self.stores.values())
        raise KeyError(f"Unknown store: {store_name}. Known stores: {known}")

    def description_template(self, template_key: str) -> str:
        if template_key in self.templates:
            return self.templates[template_key]
        lowered = normalize_key(template_key)
        for key, value in self.templates.items():
            if normalize_key(key) == lowered:
                return value
        known = ", ".join(sorted(self.templates))
        raise KeyError(f"Unknown description template: {template_key}. Known templates: {known}")


def normalize_key(value: str) -> str:
    return str(value or "").replace("\u3000", " ").strip().lower()


def default_config_dir() -> Path:
    return PROJECT_ROOT / "config"


def load_json_yaml(path: Path) -> Dict[str, Any]:
    """Load the project's JSON-compatible .yaml files without external deps."""

    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} must be JSON-compatible YAML for this dependency-free MVP: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain an object at the top level")
    return data


def load_app_config(config_dir: Optional[Path] = None) -> AppConfig:
    base = Path(config_dir) if config_dir else default_config_dir()
    _load_project_env(base.parent / ".env")
    stores_raw = load_json_yaml(base / "stores.yaml")
    workbook_raw = load_json_yaml(base / "workbook.yaml")
    ai_raw = load_json_yaml(base / "ai.yaml")

    stores: Dict[str, StoreConfig] = {}
    aliases: Dict[str, str] = {}
    for raw in stores_raw.get("stores", []):
        store = StoreConfig(
            name=raw["name"],
            status_column=str(raw["status_column"]).upper(),
            template_key=raw["template_key"],
            listing_sheet=str(raw.get("listing_sheet", "") or "").strip(),
        )
        key = normalize_key(store.name)
        stores[key] = store
        aliases[key] = key
        for alias in raw.get("aliases", []):
            aliases[normalize_key(alias)] = key

    workbook = WorkbookConfig(
        path=workbook_raw["path"],
        sheet_prefix=workbook_raw["sheet_prefix"],
        unlisted_status=workbook_raw["unlisted_status"],
        field_columns={k: str(v).upper() for k, v in workbook_raw["field_columns"].items()},
    )
    zhipu_raw = ai_raw.get("zhipu", {})
    if not isinstance(zhipu_raw, dict):
        zhipu_raw = {}
    fallback_models = ai_raw.get("fallback_models") or zhipu_raw.get("fallback_models") or []
    if isinstance(fallback_models, str):
        fallback_models = [item.strip() for item in fallback_models.split(",") if item.strip()]
    if not isinstance(fallback_models, list):
        fallback_models = []
    provider = os.environ.get("AI_PROVIDER") or ai_raw.get("provider", "openai")
    nvidia_raw = ai_raw.get("nvidia_dual", {})
    if not isinstance(nvidia_raw, dict):
        nvidia_raw = {}
    provider_key = str(provider).lower()
    if provider_key == "openai":
        openai_raw = ai_raw.get("openai", {})
        if not isinstance(openai_raw, dict):
            openai_raw = {}
        api_key_env = "OPENAI_API_KEY"
        endpoint = openai_raw.get("base_url", "https://api.openai.com/v1")
        model = openai_raw.get("model", "gpt-5.6")
        timeout = openai_raw.get("timeout_seconds", 900)
    elif provider_key in {"nvidia", "nvidia_dual", "nvidia-dual", "multi_model", "multi-model"}:
        default_api_key_env = "NVIDIA_TEXT_API_KEY"
        api_key_env = default_api_key_env
        endpoint = nvidia_raw.get("text_base_url", "")
        model = nvidia_raw.get("text_model", "")
        timeout = nvidia_raw.get("timeout_seconds", 90)
    else:
        default_api_key_env = "ZHIPU_API_KEY" if provider_key == "zhipu" else "SHOPEE_LISTING_API_KEY"
        api_key_env = ai_raw.get("api_key_env") or zhipu_raw.get("api_key_env", default_api_key_env)
        endpoint = ai_raw.get("endpoint") or zhipu_raw.get("endpoint", "")
        model = ai_raw.get("model") or zhipu_raw.get("default_model", "")
        timeout = ai_raw.get("timeout_seconds") or zhipu_raw.get("timeout_seconds", 60)
    ai = AIConfig(
        provider=provider,
        endpoint=endpoint,
        api_key_env=api_key_env,
        model=model,
        timeout_seconds=int(timeout),
        fallback_models=[str(item) for item in fallback_models],
        max_retries_per_model=int(ai_raw.get("max_retries_per_model") or zhipu_raw.get("max_retries_per_model", 2)),
        mask_api_key_in_logs=bool(ai_raw.get("mask_api_key_in_logs", zhipu_raw.get("mask_api_key_in_logs", True))),
    )

    return AppConfig(
        config_dir=base,
        stores=stores,
        aliases=aliases,
        templates=stores_raw.get("description_templates", {}),
        workbook=workbook,
        ai=ai,
    )


def add_custom_store_name(
    config_dir: Path,
    base_store_name: str,
    custom_store_name: str,
) -> tuple[StoreConfig, bool]:
    """Persist a custom store name using an existing store's workbook mapping."""

    name = " ".join(str(custom_store_name or "").split())
    if not name:
        raise ValueError("Enter a custom store name.")
    if len(name) > 100:
        raise ValueError("The custom store name must be 100 characters or fewer.")
    if any(ord(character) < 32 for character in name):
        raise ValueError("The custom store name cannot contain control characters.")

    base = Path(config_dir)
    stores_path = base / "stores.yaml"
    with _STORE_CONFIG_LOCK:
        config = load_app_config(base)
        normalized_name = normalize_key(name)
        existing_key = config.aliases.get(normalized_name)
        if existing_key in config.stores:
            return config.stores[existing_key], False

        selected_base_name = str(base_store_name or "").strip()
        if not selected_base_name:
            raise ValueError(
                "Select an existing store first so its workbook mapping can be reused."
            )
        base_store = config.store(selected_base_name)
        if not base_store.listing_sheet:
            raise ValueError(
                f'The selected store "{base_store.name}" has no listing_sheet mapping.'
            )

        raw = load_json_yaml(stores_path)
        stores = raw.setdefault("stores", [])
        if not isinstance(stores, list):
            raise ValueError("stores in config/stores.yaml must be a list.")
        templates = raw.setdefault("description_templates", {})
        if not isinstance(templates, dict):
            raise ValueError(
                "description_templates in config/stores.yaml must be an object."
            )

        stores.append(
            {
                "name": name,
                "status_column": base_store.status_column,
                "template_key": name,
                "listing_sheet": base_store.listing_sheet,
                "aliases": [name],
            }
        )
        templates[name] = ""
        stores_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        refreshed = load_app_config(base)
        return refreshed.store(name), True


def _load_project_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")
