from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.config_manager import load_app_config


class ConfigEnvOverrideTests(unittest.TestCase):
    def test_project_env_provider_is_loaded_before_ai_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "config"
            config.mkdir()
            (root / ".env").write_text("AI_PROVIDER=nvidia_dual\n", encoding="utf-8")
            (config / "ai.yaml").write_text(json.dumps({"provider": "zhipu", "nvidia_dual": {}}), encoding="utf-8")
            (config / "workbook.yaml").write_text(json.dumps({"path": "x", "sheet_prefix": "s", "unlisted_status": "未上架", "field_columns": {}}), encoding="utf-8")
            (config / "stores.yaml").write_text(json.dumps({"stores": [], "description_templates": {}}), encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                loaded = load_app_config(config)

        self.assertEqual(loaded.ai.provider, "nvidia_dual")


if __name__ == "__main__":
    unittest.main()
