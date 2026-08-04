from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.ziniao_connector import (
    _powershell_executable,
    detect_ziniao_store_name,
    discover_cdp_candidates,
    parse_cdp_processes,
    query_browser_processes,
    query_ziniao_listener_processes,
)


class ZiniaoConnectorTests(unittest.TestCase):
    def test_store_name_can_be_read_from_ziniao_extension_page(self):
        page = {
            "type": "page",
            "url": "chrome-extension://extension-id/index.html",
            "webSocketDebuggerUrl": "ws://127.0.0.1:55521/devtools/page/account",
        }
        client = Mock()
        client.evaluate.return_value = {
            "result": {
                "value": (
                    "北京\n07-29 10:52:06\n"
                    "Shopee-MY-Store-A\n"
                    "（登录账号：11****13）\n打开账号"
                )
            }
        }

        with (
            patch(
                "shopee_listing_app.browser.cdp_client.list_pages",
                return_value=[page],
            ),
            patch(
                "shopee_listing_app.browser.cdp_client.CdpClient",
                return_value=client,
            ),
        ):
            store_name = detect_ziniao_store_name(55521)

        self.assertEqual(store_name, "Shopee-MY-Store-A")
        client.connect.assert_called_once_with()
        client.close.assert_called_once_with()

    def test_parse_cdp_processes_ignores_ziniao_manager_9480(self):
        processes = [
            {
                "ProcessId": 10,
                "Name": "ziniao.exe",
                "CommandLine": "ziniao.exe --service-port=9480",
            },
            {
                "ProcessId": 11,
                "Name": "ziniaobrowser.exe",
                "CommandLine": "ziniaobrowser.exe --remote-debugging-port=45678 --user-data-dir=x",
            },
        ]

        ports = parse_cdp_processes(processes)

        self.assertEqual(len(ports), 1)
        self.assertEqual(ports[0].port, 45678)
        self.assertEqual(ports[0].process_id, 11)

    def test_parse_cdp_processes_deduplicates_child_processes_by_port(self):
        processes = [
            {
                "ProcessId": 21,
                "Name": "ziniaobrowser.exe",
                "CommandLine": "ziniaobrowser.exe --type=renderer --remote-debugging-port=45678",
            },
            {
                "ProcessId": 20,
                "Name": "ziniaobrowser.exe",
                "CommandLine": "ziniaobrowser.exe --remote-debugging-port=45678 --user-data-dir=x",
            },
            {
                "ProcessId": 22,
                "Name": "ziniaobrowser.exe",
                "CommandLine": "ziniaobrowser.exe --type=gpu-process --remote-debugging-port=45678",
            },
        ]

        ports = parse_cdp_processes(processes)

        self.assertEqual(len(ports), 1)
        self.assertEqual(ports[0].port, 45678)
        self.assertEqual(ports[0].process_id, 20)

    def test_query_browser_processes_decodes_utf8_bytes_itself(self):
        raw_json = (
            '[{"ProcessId":12,"Name":"ziniaobrowser.exe",'
            '"CommandLine":"紫鸟 --remote-debugging-port=45679"}]'
        ).encode("utf-8")

        def fake_run(_command, **kwargs):
            self.assertFalse(kwargs.get("text", False))
            self.assertEqual(Path(_command[0]).name.lower(), "powershell.exe")
            return subprocess.CompletedProcess(_command, 0, stdout=raw_json, stderr=b"")

        with patch("shopee_listing_app.ziniao_connector.subprocess.run", fake_run):
            processes = query_browser_processes()

        self.assertEqual(processes[0]["ProcessId"], 12)
        self.assertIn("紫鸟", processes[0]["CommandLine"])

    def test_query_browser_processes_timeout_uses_listener_fallback(self):
        with patch(
            "shopee_listing_app.ziniao_connector.subprocess.run",
            side_effect=subprocess.TimeoutExpired("powershell", 15),
        ):
            self.assertEqual(query_browser_processes(), [])

    def test_windows_powershell_is_resolved_without_relying_on_path(self):
        executable = Path(_powershell_executable())

        self.assertEqual(executable.name.lower(), "powershell.exe")
        self.assertTrue(executable.is_file())

    def test_listener_fallback_matches_only_ziniao_browser_processes(self):
        process_json = (
            '[{"ProcessId":101,"Name":"ziniaobrowser","WindowTitle":"Store A"},'
            '{"ProcessId":102,"Name":"ziniaobrowser","WindowTitle":"Store B"}]'
        ).encode("utf-8")
        netstat_output = (
            "  TCP    127.0.0.1:55521    0.0.0.0:0    LISTENING    101\r\n"
            "  TCP    127.0.0.1:55561    0.0.0.0:0    LISTENING    102\r\n"
            "  TCP    127.0.0.1:9222     0.0.0.0:0    LISTENING    999\r\n"
        ).encode("utf-8")

        def fake_run(command, **_kwargs):
            if Path(command[0]).name.lower() == "powershell.exe":
                return subprocess.CompletedProcess(command, 0, stdout=process_json, stderr=b"")
            return subprocess.CompletedProcess(command, 0, stdout=netstat_output, stderr=b"")

        with patch("shopee_listing_app.ziniao_connector.subprocess.run", fake_run):
            processes = query_ziniao_listener_processes()

        self.assertEqual([item["ProcessId"] for item in processes], [101, 102])
        self.assertIn("--remote-debugging-port=55521", processes[0]["CommandLine"])
        self.assertEqual(processes[0]["WindowTitle"], "Store A")

    def test_discovery_uses_listener_fallback_when_wmi_is_unavailable(self):
        fallback_process = {
            "ProcessId": 101,
            "Name": "ziniaobrowser",
            "CommandLine": "ziniaobrowser.exe --remote-debugging-port=55521",
            "WindowTitle": "Shopee Store A",
        }
        metadata = {
            "Browser": "Chrome/138",
            "webSocketDebuggerUrl": "ws://127.0.0.1:55521/devtools/browser/test",
        }

        with (
            patch(
                "shopee_listing_app.ziniao_connector.query_browser_processes",
                return_value=[],
            ),
            patch(
                "shopee_listing_app.ziniao_connector.query_ziniao_listener_processes",
                return_value=[fallback_process],
            ),
            patch(
                "shopee_listing_app.ziniao_connector.probe_json_version",
                return_value=metadata,
            ),
        ):
            candidates = discover_cdp_candidates(verify=True)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].port, 55521)
        self.assertEqual(candidates[0].window_title, "Shopee Store A")
        self.assertTrue(candidates[0].verified)

    def test_discovery_prefers_listener_without_running_wmi_query(self):
        listener_process = {
            "ProcessId": 101,
            "Name": "ziniaobrowser",
            "CommandLine": "ziniaobrowser.exe --remote-debugging-port=55521",
            "WindowTitle": "Shopee Store A",
        }
        with (
            patch(
                "shopee_listing_app.ziniao_connector.query_ziniao_listener_processes",
                return_value=[listener_process],
            ),
            patch(
                "shopee_listing_app.ziniao_connector.query_browser_processes",
                side_effect=AssertionError("WMI query should not run"),
            ),
            patch(
                "shopee_listing_app.ziniao_connector.probe_json_version",
                return_value={"Browser": "Chrome/138"},
            ),
        ):
            candidates = discover_cdp_candidates(verify=True)

        self.assertEqual([item.port for item in candidates], [55521])


if __name__ == "__main__":
    unittest.main()
