"""独立进程验证无 Qt CLI；主配置与游戏配置均在临时目录。"""

import json
import os
import queue
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, call, create_autospec

from jsonrpcserver import dispatch_to_serializable

from src.headless import _parse_json, rpc_methods
from src.service.app_service import AppService
from src.update.runtime import FileLease, UpdateBusyError
from src.utils.utils_yaml import load_yaml
from tests.support.headless import PROJECT_ROOT, HeadlessFixture


def request(method, params=None, request_id=1):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {} if params is None else params,
    }


def mock_service():
    service = Mock(spec=AppService)
    instance = object.__new__(AppService)
    for name in dir(AppService):
        if not name.startswith("_") and callable(getattr(AppService, name)):
            service.attach_mock(create_autospec(getattr(instance, name)), name)
    return service


def handle_request(service, payload):
    return dispatch_to_serializable(
        json.dumps(payload), methods=rpc_methods(service), deserializer=_parse_json
    )


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
        self.fixture = HeadlessFixture(self.root)
        self.native = self.fixture.native
        self.initial = self.fixture.initial
        self.env = {
            **os.environ,
            "PYTHONIOENCODING": "ascii",
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    def command(self, *args):
        return self.fixture.command(*args)

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
        self.assertEqual(responses[1]["result"]["dailies"][0]["task"], "模拟领域")
        self.assertIsNone(responses[2]["result"])
        written = responses[3]["result"]
        daily = written["dailies"][0]
        self.assertEqual(set(daily), {"name", "task", "sequence", "enabled", "options"})
        self.assertEqual(daily["name"], "每日任务")
        self.assertEqual(daily["task"], "凝素领域")
        self.assertEqual(daily["sequence"], 1)
        self.assertEqual(written["weeklies"][0]["name"], "幻梦游园")
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

    def test_adapter_rejections_leave_native_file_unchanged(self):
        before = self.native.read_bytes()
        cases = [
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
            self.assertEqual(response["error"]["code"], -32002, response)
            self.assertTrue(response["error"]["data"]["refresh_required"])
        self.assertEqual(before, self.native.read_bytes())

    def test_daily_defaults_and_noops_return_null(self):
        before = self.native.read_bytes()
        cases = [
            {"script_name": "ok-ww"},
            {"script_name": "ok-ww", "daily_name": None, "task_name": None},
            selection(task_name=None),
            selection(task_name=""),
            selection(task_name="未选择"),
            selection(script_name="missing"),
            selection(script_name="自定义脚本"),
        ]
        result, responses = self.serve(
            [request("daily.select", params, i) for i, params in enumerate(cases)]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            responses,
            [{"jsonrpc": "2.0", "id": i, "result": None} for i in range(len(cases))],
        )
        self.assertEqual(before, self.native.read_bytes())

    def test_call_accepts_static_sequence_display_name(self):
        result, responses = self.run_cli(
            ["call", "daily.select"],
            json.dumps(selection(sequence="梦州-迅刀"), ensure_ascii=False),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(responses, [{"jsonrpc": "2.0", "id": 1, "result": None}])
        self.assertEqual(
            json.loads(self.native.read_text(encoding="utf-8")),
            {
                **self.initial,
                "Which to Farm": "Forgery Challenge",
                "Which Forgery Challenge to Farm": 1,
            },
        )

    def test_call_exit_status_and_utf8(self):
        result, responses = self.run_cli(["call", "app.snapshot"], "{}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(responses), 1)
        self.assertIn("鸣潮", result.stdout)
        self.assertEqual(responses[0]["id"], 1)
        result, responses = self.run_cli(["call", "daily.select"], "{}")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(responses[0]["error"]["code"], -32602)

    def test_call_invalid_json_returns_parse_error(self):
        result, responses = self.run_cli(["call", "app.snapshot"], "oops")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(responses[0]["jsonrpc"], "2.0")
        self.assertIsNone(responses[0]["id"])
        self.assertEqual(responses[0]["error"]["code"], -32700)

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
        requests = []
        for i, value in enumerate((True, 1, False, 0)):
            requests.extend(
                [
                    request(
                        "daily.select",
                        selection(
                            script_name="March7th-Launcher",
                            task_name="每日任务",
                            sequence=value,
                        ),
                        i * 2,
                    ),
                    request(
                        "script.view", {"script_name": "March7th-Launcher"}, i * 2 + 1
                    ),
                ]
            )
        result, responses = self.serve(requests)
        self.assertEqual(result.returncode, 0, result.stderr)
        for i in (0, 4):
            self.assertIsNone(responses[i]["result"])
        for i in (2, 6):
            self.assertEqual(responses[i]["error"]["code"], -32002)
        for i, expected in ((1, True), (3, True), (5, False), (7, False)):
            self.assertIs(responses[i]["result"]["dailies"][0]["sequence"], expected)
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
        requests = []
        for i, value in enumerate(("已删除的副本", "副本乙")):
            requests.extend(
                [
                    request(
                        "daily.select",
                        selection(
                            script_name="ok-ef", task_name="干员养成", sequence=value
                        ),
                        i * 2,
                    ),
                    request("script.view", {"script_name": "ok-ef"}, i * 2 + 1),
                ]
            )
        result, responses = self.serve(requests)
        self.assertEqual(result.returncode, 0, result.stderr)
        for i, expected in ((0, "已删除的副本"), (2, "副本乙")):
            self.assertIsNone(responses[i]["result"])
            daily = responses[i + 1]["result"]["dailies"][0]
            self.assertEqual(daily["task"], expected)
            self.assertIs(daily["enabled"], True)
        self.assertEqual(
            json.loads(native.read_text(encoding="utf-8")),
            {"体力本": "副本乙", "⭐刷体力": True, "untouched": 42},
        )
        result, responses = self.serve(
            [
                request(
                    "daily.enable",
                    {
                        "script_name": "ok-ef",
                        "daily_name": "每日任务",
                        "enabled": False,
                    },
                ),
                request(
                    "daily.enable",
                    {"script_name": "ok-ef", "daily_name": "每日任务", "enabled": 1},
                    2,
                ),
                request("script.view", {"script_name": "ok-ef"}, 3),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(responses[0]["result"])
        self.assertEqual(responses[1]["error"]["code"], -32002)
        self.assertIs(responses[2]["result"]["dailies"][0]["enabled"], False)
        self.assertEqual(
            json.loads(native.read_text(encoding="utf-8")),
            {"体力本": "副本乙", "⭐刷体力": False, "untouched": 42},
        )

    def test_task_mutations_keep_adapter_noops_and_day_validation(self):
        before = self.native.read_bytes()
        payloads = [
            request(
                "daily.enable",
                {"script_name": "ok-ww", "daily_name": "每日任务", "enabled": False},
            ),
            request(
                "weekly.select",
                {
                    "script_name": "ok-ww",
                    "weekly_name": "不存在",
                    "task_name": "不存在",
                },
            ),
            request(
                "weekly.select",
                {
                    "script_name": "ok-ww",
                    "weekly_name": "幻梦游园",
                    "task_name": "不存在",
                },
            ),
        ] + [
            request(
                "weekly.start",
                {"script_name": "ok-ww", "weekly_name": "幻梦游园", "start_day": value},
            )
            for value in (-1, 8, True)
        ]
        result, responses = self.serve(payloads)
        self.assertEqual(result.returncode, 0, result.stderr)
        for response in responses[:3]:
            self.assertIsNone(response["result"])
        for response in responses[3:]:
            self.assertEqual(response["error"]["code"], -32002)
        self.assertEqual(self.native.read_bytes(), before)
        self.assertEqual(
            load_yaml(str(self.root / "config/weekly.yml"))["weekly_start"]["ok-ww"][
                "幻梦游园"
            ],
            1,
        )

    def test_weekly_start_returns_null_and_preserves_unknown_entry(self):
        result, responses = self.serve(
            [
                request(
                    "weekly.start",
                    {"script_name": "ok-ww", "weekly_name": "幻梦游园", "start_day": 0},
                ),
                request("script.view", {"script_name": "ok-ww"}, 2),
                request(
                    "weekly.start",
                    {"script_name": "ok-ww", "weekly_name": "未知周常", "start_day": 4},
                    3,
                ),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(responses[0]["result"])
        self.assertEqual(responses[1]["result"]["weeklies"][0]["start_day"], 0)
        self.assertIsNone(responses[2]["result"])
        self.assertEqual(
            load_yaml(str(self.root / "config/weekly.yml"))["weekly_start"]["ok-ww"],
            {"幻梦游园": 0, "未知周常": 4},
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
        self.assertEqual([r["error"]["code"] for r in responses[:3]], [-32700] * 3)
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
        self.assertEqual(responses[0]["error"]["code"], -32002)
        self.assertTrue(responses[0]["error"]["data"]["refresh_required"])
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
        self.assertEqual(responses[0]["error"]["code"], -32004)
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
                        response["result"]["dailies"][0]["sequence"],
                        sequence,
                    )
                with (
                    self.assertRaises(UpdateBusyError),
                    FileLease(self.root / ".update/runtime.lock"),
                ):
                    self.fail("会话未持有运行租约")
                process.stdin.close()
                self.assertEqual(process.wait(timeout=10), 0)
                lock_path = self.root / ".update/runtime.lock"
                with (
                    FileLease(lock_path),
                    self.assertRaises(UpdateBusyError),
                    FileLease(lock_path, shared=True),
                ):
                    self.fail("会话退出后取得的独占锁未阻止共享锁")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()
                if process.stdout is not None:
                    process.stdout.close()
                reader.join(timeout=5)

    def test_jsonrpc_batch_and_notification_preserve_writes_and_session(self):
        notification = request("daily.select", selection())
        del notification["id"]
        result, responses = self.serve(
            [
                notification,
                [
                    request("script.view", {"script_name": "ok-ww"}, request_id=""),
                    request("unknown", request_id=2),
                ],
                request("app.snapshot", request_id="after"),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(responses), 2)
        self.assertEqual(len(responses[0]), 2)
        view, missing = responses[0]
        self.assertEqual(view["id"], "")
        self.assertEqual(view["result"]["dailies"][0]["sequence"], 1)
        self.assertEqual(missing["error"]["code"], -32601)
        self.assertEqual(responses[1]["id"], "after")
        self.assertEqual(
            json.loads(self.native.read_text(encoding="utf-8"))[
                "Which Forgery Challenge to Farm"
            ],
            1,
        )


class ProtocolValidationTests(unittest.TestCase):
    def test_library_binds_positional_and_default_parameters(self):
        service = mock_service()
        service.select_daily.return_value = None
        response = handle_request(service, request("daily.select", ["脚本"]))
        self.assertEqual(response, {"jsonrpc": "2.0", "id": 1, "result": None})
        service.select_daily.assert_called_once_with("脚本")
        service.app_snapshot.return_value = {"scripts": []}
        response = handle_request(
            service, {"jsonrpc": "2.0", "method": "app.snapshot", "id": ""}
        )
        self.assertEqual(response["result"], {"scripts": []})
        self.assertEqual(response["id"], "")
        service.app_snapshot.assert_called_once_with()

    def test_invalid_envelopes_and_params_never_dispatch(self):
        cases = [
            ([], -32600),
            ({**request("app.snapshot"), "extra": 0}, -32600),
            (
                {**request("app.snapshot"), "jsonrpc": True},
                -32600,
            ),
            ({**request("app.snapshot"), "jsonrpc": "1.0"}, -32600),
            (request("app.snapshot", request_id=True), -32600),
            (request("run.start"), -32601),
            (request("app.snapshot", [1]), -32602),
            (request("app.snapshot", {"extra": 0}), -32602),
            (request("script.view"), -32602),
            (request("daily.select", {"task_name": "材料"}), -32602),
            (request("daily.select", selection(extra=True)), -32602),
        ]
        service = mock_service()
        for payload, code in cases:
            with self.subTest(payload=payload):
                response = handle_request(service, payload)
                self.assertEqual(response["error"]["code"], code)
        self.assertEqual(service.mock_calls, [])

    def test_write_requests_forward_values_and_never_query(self):
        cases = [
            ("daily.select", "select_daily", {"script_name": "脚本"}),
            (
                "daily.select",
                "select_daily",
                selection(daily_name=None, task_name=None),
            ),
            ("daily.select", "select_daily", selection(task_name="")),
            ("daily.select", "select_daily", selection(sequence="梦州-迅刀")),
            ("daily.select", "select_daily", selection(sequence=True)),
            ("daily.select", "select_daily", selection(sequence=1)),
            ("daily.select", "select_daily", selection(sequence=None)),
            (
                "daily.enable",
                "enable_daily",
                {"script_name": "脚本", "daily_name": "日常", "enabled": False},
            ),
            (
                "weekly.select",
                "select_weekly",
                {"script_name": "脚本", "weekly_name": "周常", "task_name": "副本"},
            ),
            (
                "weekly.start",
                "start_weekly",
                {"script_name": "脚本", "weekly_name": "周常", "start_day": 0},
            ),
        ]
        for method, attribute, params in cases:
            with self.subTest(method=method, params=params):
                service = mock_service()
                getattr(service, attribute).return_value = None
                service.script_view.side_effect = OSError("查询失败")
                response = handle_request(service, request(method, params))
                self.assertEqual(response, {"jsonrpc": "2.0", "id": 1, "result": None})
                self.assertEqual(
                    service.mock_calls, [getattr(call, attribute)(**params)]
                )
                self.assertEqual(
                    json.dumps(getattr(service, attribute).call_args.kwargs),
                    json.dumps(params),
                )

    def test_failure_after_write_does_not_claim_rollback(self):
        service = mock_service()
        service.select_daily.side_effect = OSError("second write failed")
        with self.assertLogs("src.headless", level="ERROR") as logs:
            response = handle_request(service, request("daily.select", selection()))
        self.assertTrue(response["error"]["data"]["refresh_required"])
        self.assertIn("OSError", "".join(logs.output))
        service.select_daily.assert_called_once_with(**selection())

    def test_read_failure_does_not_require_refresh(self):
        service = mock_service()
        service.script_view.side_effect = OSError("query failed")
        with self.assertLogs("src.headless", level="ERROR"):
            response = handle_request(
                service, request("script.view", {"script_name": "脚本"})
            )
        self.assertEqual(response["error"]["code"], -32002)
        self.assertFalse(response["error"]["data"]["refresh_required"])
