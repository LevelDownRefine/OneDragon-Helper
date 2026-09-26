"""独立进程验证无 Qt CLI；主配置与游戏配置均在临时目录。"""

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from src.headless import handle_request
from src.update.runtime import FileLease, UpdateBusyError
from src.utils.utils_yaml import load_yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 只在测试进程替换根目录；在任何业务模块导入前生效，不改产品路径规则。
CHILD = """
import importlib.abc
import runpy
import sys
from unittest.mock import patch

class NoGui(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('PySide6', 'shiboken6') or fullname.startswith('src.gui'):
            raise AssertionError('CLI 加载了 GUI: ' + fullname)

sys.meta_path.insert(0, NoGui())
root = sys.argv.pop(1)
with patch('src.utils.get_root_dir', return_value=root):
    runpy.run_module('src.headless', run_name='__main__')
"""


def request(method, params=None, request_id=1):
    return {
        "protocol_version": 1,
        "id": request_id,
        "method": method,
        "params": {} if params is None else params,
    }


def selection(**changes):
    return {
        "script_name": "ok-ww",
        "daily_name": "每日任务",
        "task_name": "凝素领域",
        "sequence": 1,
        **changes,
    }


class HeadlessProcessTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        config_dir = self.root / "config"
        config_dir.mkdir()
        for name in (
            "schedule.example.yml",
            "weekly.example.yml",
            "daily_task_list.yml",
            "weekly_task_list.yml",
        ):
            shutil.copyfile(PROJECT_ROOT / "config" / name, config_dir / name)
        config_dir.joinpath("config.example.yml").write_text(
            "script_list:\n"
            "- display_name: 鸣潮\n  script_path: scripts/ok-ww.exe\n"
            "- display_name: 自定义脚本\n  script_path: scripts/custom.py\n",
            encoding="utf-8",
        )
        scripts = self.root / "scripts"
        scripts.mkdir()
        scripts.joinpath("ok-ww.exe").touch()
        scripts.joinpath("custom.py").touch()
        self.native = scripts / "data/apps/ok-ww/working/configs/DailyTask.json"
        self.native.parent.mkdir(parents=True)
        self.initial = {
            "Which to Farm": "Simulation Challenge",
            "Which Forgery Challenge to Farm": 20,
            "Which Tacet Suppression to Farm": 19,
            "Material Selection": "Shell Credit",
            "untouched": {"中文": [1, 2, 3]},
        }
        self.native.write_text(
            json.dumps(self.initial, ensure_ascii=False), encoding="utf-8"
        )
        self.env = {
            **os.environ,
            "PYTHONIOENCODING": "ascii",
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    def command(self, *args):
        return [sys.executable, "-c", CHILD, str(self.root), *args]

    def run_cli(self, args, payload):
        result = subprocess.run(
            self.command(*args),
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
            env=self.env,
            timeout=30,
        )
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        return result, responses

    def serve(self, requests):
        return self.run_cli(
            ["serve", "--stdio"],
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in requests),
        )

    def test_task_card_round_trip_without_gui(self):
        result, responses = self.serve(
            [
                request("app.snapshot", request_id="列表"),
                request("script.view", {"script_name": "ok-ww"}, 2),
                request("daily.select", selection(), 3),
                request("script.view", {"script_name": "ok-ww"}, 4),
                request("script.view", {"script_name": "自定义脚本"}, 5),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([item["id"] for item in responses], ["列表", 2, 3, 4, 5])
        self.assertEqual(
            [item["script_name"] for item in responses[0]["result"]["scripts"]],
            ["ok-ww", "自定义脚本"],
        )
        self.assertEqual(
            responses[1]["result"]["dailies"][0]["selected"]["task_name"], "模拟领域"
        )
        written = responses[2]["result"]
        self.assertEqual(written, responses[3]["result"])
        self.assertEqual(
            written["dailies"][0]["selected"], {"task_name": "凝素领域", "sequence": 1}
        )
        self.assertEqual(written["weeklies"][0]["weekly_name"], "幻梦游园")
        self.assertEqual(written["weeklies"][0]["start_day"], 1)
        self.assertEqual(responses[4]["result"]["dailies"], [])
        self.assertFalse(responses[4]["result"]["script"]["adapted"])
        expected = {
            **self.initial,
            "Which to Farm": "Forgery Challenge",
            "Which Forgery Challenge to Farm": 1,
        }
        self.assertEqual(json.loads(self.native.read_text(encoding="utf-8")), expected)
        self.assertIn("config 已更新", result.stderr)

    def test_invalid_selections_leave_native_file_unchanged(self):
        before = self.native.read_bytes()
        cases = [
            selection(script_name="missing"),
            selection(script_name="自定义脚本"),
            selection(daily_name="missing"),
            selection(task_name="missing"),
            selection(sequence=None),
            selection(sequence=999999),
            selection(sequence="1"),
            selection(sequence=True),
        ]
        result, responses = self.serve(
            [request("daily.select", params, i) for i, params in enumerate(cases)]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(responses), len(cases))
        for response in responses:
            self.assertEqual(response["error"]["code"], "invalid_params", response)
        self.assertEqual(before, self.native.read_bytes())

    def test_call_exit_status_and_utf8(self):
        result, responses = self.run_cli(["call", "app.snapshot"], "{}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(responses), 1)
        self.assertIn("鸣潮", result.stdout)
        self.assertEqual(responses[0]["id"], 1)
        result, responses = self.run_cli(["call", "daily.select"], "{}")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(responses[0]["error"]["code"], "invalid_params")

    def test_boolean_physical_values_are_distinct_from_integers(self):
        with self.root.joinpath("config/config.example.yml").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(
                "- display_name: 崩铁\n  script_path: scripts/March7th-Launcher.exe\n"
            )
        self.root.joinpath("scripts/March7th-Launcher.exe").touch()
        native = self.root / "scripts/config.yaml"
        native.write_text(
            "build_target_enable: false\npower_enable: true\n", encoding="utf-8"
        )
        result, responses = self.serve(
            [
                request(
                    "daily.select",
                    selection(
                        script_name="March7th-Launcher",
                        task_name="每日任务",
                        sequence=value,
                    ),
                    i,
                )
                for i, value in enumerate((True, 1, False, 0))
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIs(
            responses[0]["result"]["dailies"][0]["selected"]["sequence"], True
        )
        self.assertIs(
            responses[2]["result"]["dailies"][0]["selected"]["sequence"], False
        )
        for i in (1, 3):
            self.assertEqual(responses[i]["error"]["code"], "invalid_params")
        self.assertEqual(
            load_yaml(str(native)), {"build_target_enable": False, "power_enable": True}
        )

    def test_resource_selection_reuses_enable_behavior(self):
        with self.root.joinpath("config/config.example.yml").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write("- display_name: 终末地\n  script_path: scripts/ok-ef.exe\n")
        self.root.joinpath("scripts/ok-ef.exe").touch()
        working = self.root / "scripts/data/apps/ok-ef/working"
        working.joinpath("configs").mkdir(parents=True)
        working.joinpath("assets/data").mkdir(parents=True)
        native = working / "configs/DailyTask.json"
        native.write_text(
            json.dumps({"体力本": "旧副本", "⭐刷体力": False, "untouched": 42}),
            encoding="utf-8",
        )
        working.joinpath("assets/data/world_map.json").write_text(
            json.dumps(
                {
                    "stages_dict": {
                        name: ["副本甲", "副本乙"]
                        for name in (
                            "干员养成",
                            "武器养成",
                            "危境再现",
                            "危境预演",
                            "能量淤积点",
                        )
                    }
                }
            ),
            encoding="utf-8",
        )
        result, responses = self.serve(
            [
                request(
                    "daily.select",
                    selection(
                        script_name="ok-ef", task_name="干员养成", sequence=value
                    ),
                    i,
                )
                for i, value in enumerate(("已删除的副本", "副本乙"))
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(responses[0]["error"]["code"], "invalid_params")
        daily = responses[1]["result"]["dailies"][0]
        self.assertEqual(daily["selected"]["task_name"], "副本乙")
        self.assertIs(daily["enabled"], True)
        self.assertEqual(
            json.loads(native.read_text(encoding="utf-8")),
            {"体力本": "副本乙", "⭐刷体力": True, "untouched": 42},
        )

    def test_weekly_disabled_and_unset_are_distinct(self):
        for content, expected in (("{ok-ww: {幻梦游园: 0}}", 0), ("{}", None)):
            with self.subTest(expected=expected):
                self.root.joinpath("config/weekly.yml").write_text(
                    f"weekly_start: {content}\nweekly_timeouts: {{}}\n",
                    encoding="utf-8",
                )
                result, responses = self.run_cli(
                    ["call", "script.view"], '{"script_name":"ok-ww"}'
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    responses[0]["result"]["weeklies"][0]["start_day"], expected
                )

    def test_malformed_json_does_not_end_session(self):
        result, responses = self.run_cli(
            ["serve", "--stdio"],
            'oops\n{"id":1,"id":2}\n{"value":NaN}\n'
            + json.dumps(request("app.snapshot"))
            + "\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [r["error"]["code"] for r in responses[:3]], ["parse_error"] * 3
        )
        self.assertIn("result", responses[3])

    def test_missing_game_config_reports_failure_and_keeps_session(self):
        self.native.unlink()
        result, responses = self.serve(
            [
                request("daily.select", selection()),
                request("app.snapshot", request_id=2),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(responses[0]["error"]["code"], "operation_failed")
        self.assertTrue(responses[0]["error"]["refresh_required"])
        self.assertIn("AssertionError", result.stderr)
        self.assertIn("result", responses[1])

    def test_update_gate_precedes_configuration_initialization(self):
        update_dir = self.root / ".update"
        update_dir.mkdir()
        update_dir.joinpath("transaction.json").write_text(
            '{"phase":"installing"}', encoding="utf-8"
        )
        result, responses = self.run_cli(["call", "app.snapshot"], "{}")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(responses[0]["error"]["code"], "session_failed")
        self.assertFalse(self.root.joinpath("config/config.yml").exists())

    def test_external_changes_are_visible_in_same_session(self):
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            process = subprocess.Popen(
                self.command("serve", "--stdio"),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=errors,
                text=True,
                encoding="utf-8",
                cwd=PROJECT_ROOT,
                env=self.env,
            )
            try:
                assert process.stdout is not None and process.stdin is not None
                responses = queue.Queue()

                def read_responses():
                    for line in process.stdout:
                        responses.put(line)

                reader = threading.Thread(target=read_responses, daemon=True)
                reader.start()
                for sequence in (1, 2):
                    state = {
                        **self.initial,
                        "Which to Farm": "Forgery Challenge",
                        "Which Forgery Challenge to Farm": sequence,
                    }
                    self.native.write_text(json.dumps(state), encoding="utf-8")
                    process.stdin.write(
                        json.dumps(
                            request("script.view", {"script_name": "ok-ww"}, sequence)
                        )
                        + "\n"
                    )
                    process.stdin.flush()
                    response = json.loads(responses.get(timeout=15))
                    self.assertEqual(
                        response["result"]["dailies"][0]["selected"]["sequence"],
                        sequence,
                    )
                with (
                    self.assertRaises(UpdateBusyError),
                    FileLease(self.root / ".update/runtime.lock"),
                ):
                    self.fail("会话未持有运行租约")
                process.stdin.close()
                self.assertEqual(process.wait(timeout=10), 0)
                with FileLease(self.root / ".update/runtime.lock") as lease:
                    self.assertIsNotNone(lease.stream)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()
                if process.stdout is not None:
                    process.stdout.close()
                reader.join(timeout=5)


class ProtocolValidationTests(unittest.TestCase):
    def test_invalid_envelopes_and_params_never_dispatch(self):
        cases = [
            ([], "invalid_request"),
            ({**request("app.snapshot"), "extra": 0}, "invalid_request"),
            (
                {**request("app.snapshot"), "protocol_version": True},
                "unsupported_version",
            ),
            ({**request("app.snapshot"), "protocol_version": 2}, "unsupported_version"),
            (request("app.snapshot", request_id=True), "invalid_request"),
            (request("app.snapshot", request_id=""), "invalid_request"),
            (request("run.start"), "method_not_found"),
            (request("app.snapshot", []), "invalid_params"),
            (request("app.snapshot", {"extra": 0}), "invalid_params"),
            (request("script.view", {"script_name": 3}), "invalid_params"),
            (request("script.view", {"script_name": " "}), "invalid_params"),
            (request("daily.select", selection(sequence=1.0)), "invalid_params"),
        ]
        service = Mock()
        for payload, code in cases:
            with self.subTest(payload=payload):
                response = handle_request(service, payload)
                self.assertEqual(response["error"]["code"], code)
        self.assertEqual(service.mock_calls, [])

    def test_failure_after_write_does_not_claim_rollback(self):
        service = Mock()
        service.select_daily.side_effect = OSError("second write failed")
        with self.assertLogs("src.headless", level="ERROR") as logs:
            response = handle_request(service, request("daily.select", selection()))
        self.assertTrue(response["error"]["refresh_required"])
        self.assertIn("OSError", "".join(logs.output))
        service.select_daily.assert_called_once_with(**selection())
