from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LauncherScriptTests(unittest.TestCase):
    def test_gui_launcher_prefers_venv_and_rejects_wecom_python(self):
        script = (ROOT / "start_app.bat").read_text(encoding="utf-8")

        self.assertIn(".venv\\Scripts\\python.exe", script)
        self.assertIn(".runtime\\python.exe", script)
        self.assertIn("py -3", script)
        self.assertIn("PYTHONHOME=", script)
        self.assertIn("PYTHONUTF8=1", script)
        self.assertIn("PYTHONIOENCODING=utf-8", script)
        self.assertIn("chcp 65001", script)
        self.assertIn("WeComAgent", script)
        self.assertIn("--check", script)
        self.assertNotIn("5.0.9.6029", script)

    def test_setup_script_can_create_project_venv(self):
        script = (ROOT / "setup_env.bat").read_text(encoding="utf-8")
        portable_setup = (ROOT / "scripts" / "setup_portable_python.ps1").read_text(encoding="utf-8")

        self.assertIn("-m venv", script)
        self.assertIn(".venv", script)
        self.assertIn("PYTHONHOME=", script)
        self.assertIn("python-3.12.10-embed-amd64.zip", portable_setup)
        self.assertIn("FE8EF205F2E9C3BA44D0CF9954E1ABD3", portable_setup)
        self.assertIn("Expand-Archive", portable_setup)


if __name__ == "__main__":
    unittest.main()
