"""独立进程验证无 Qt CLI；主配置与游戏配置均在临时目录。"""

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, create_autospec, patch

from jsonrpcserver import dispatch_to_serializable

from src.headless import (
    InvalidParams,
    _daily_task,
    _parse_json,
    _parse_run_options,
    main,
    rpc_methods,
)
from src.service.app_service import AppService
from src.service.daily_plan import DailyPlanOptions
from src.service.schedule import RunOptions, StartupOptions
from src.service.script_service import ScriptEdit
from src.update.runtime import FileLease, UpdateBusyError
from src.utils.utils_shutdown import RUST_CONFIRM_ENV
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
    service.jobs = SimpleNamespace(running=False)
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
    def test_call_invalid_json_returns_parse_error(self):
        result, responses = self.run_cli(["call", "app.snapshot"], "oops")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(responses[0]["jsonrpc"], "2.0")
        self.assertIsNone(responses[0]["id"])
        self.assertEqual(responses[0]["error"]["code"], -32700)

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

    def test_local_update_info_without_qt_or_network(self):
        result, responses = self.serve([request("update.view")])
        self.assertEqual(result.returncode, 0, result.stderr)
        state = responses[0]["result"]
        self.assertEqual(state["version"], "源码运行")
        self.assertTrue(state["unavailable_reason"])
        self.assertIsNone(state["release"])
        self.assertIsNone(state["prepared_version"])
        for method in (
            "update.check",
            "update.download",
            "update.install",
            "job.cancel",
        ):
            result, responses = self.run_cli(["call", method], "{}")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(responses[0]["error"]["code"], -32600)

    def test_daily_plan_cli_and_independent_entry_without_qt(self):
        plan = DailyPlanOptions(
            True, "09:20", RunOptions(mute_enabled=True, close_running_enabled=False)
        )
        command = self.command("serve", "--stdio")
        command[2] = command[2].replace(
            "with patch('src.utils.get_root_dir', return_value=root):",
            """
with patch('src.utils.get_root_dir', return_value=root), patch('src.utils.utils_shutdown.rust_shutdown_supported', return_value=True), patch('src.service.daily_plan.WindowsDailyTask') as task:
    from src.service.daily_plan import DailyTaskState
    task.return_value.read.return_value = DailyTaskState()
""",
        )
        result = subprocess.run(
            command,
            input=json.dumps(request("plan.save", {"plan": asdict(plan)}))
            + "\n"
            + json.dumps(request("plan.view", request_id=2))
            + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
            env=self.env,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(responses[0]["result"], None)
        self.assertEqual(responses[1]["result"]["plan"], asdict(plan))
        self.assertEqual(responses[1]["result"]["state"]["exists"], False)
        self.assertIsNone(responses[1]["result"]["state_error"])
        self.assertTrue(responses[1]["result"]["shutdown_supported"])
        command = self.command("daily", "--shutdown-ui", "fake-rust.exe")
        command[2] = command[2].replace(
            "with patch('src.utils.get_root_dir', return_value=root):",
            """
def record(keys, target, **kwargs):
    import json,os
    from pathlib import Path
    from src.utils.utils_shutdown import RUST_CONFIRM_ENV
    Path(root, 'daily-worker.json').write_text(json.dumps({'keys':sorted(keys),'options':kwargs,'frontend':os.environ[RUST_CONFIRM_ENV]}),encoding='utf-8')
with patch('src.utils.get_root_dir', return_value=root), patch('src.service.daily_plan.chain_service.schedule_run', side_effect=record):
""",
        )
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
            env=self.env,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        recorded = json.loads(
            (self.root / "daily-worker.json").read_text(encoding="utf-8")
        )
        self.assertEqual(recorded["keys"], ["ok-ww", "自定义脚本"])
        self.assertEqual(recorded["options"]["chain_name"], "plan")
        self.assertTrue(recorded["options"]["mute"])
        self.assertEqual(recorded["frontend"], "fake-rust.exe")

    def test_global_settings_round_trip_and_saved_run_without_qt(self):
        options = asdict(RunOptions(mute_enabled=True, close_running_enabled=False))
        result, responses = self.serve(
            [
                request("settings.view"),
                request(
                    "settings.startup_save",
                    {"options": {"enabled": False, "delay_seconds": 90}},
                    2,
                ),
                request("settings.run_save", {"options": options}, 3),
                request("startup.view", request_id=4),
                request("run.saved", {"script_names": ["ok-ww"]}, 5),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all("result" in response for response in responses), responses)
        self.assertEqual(
            responses[3]["result"]["startup"], {"enabled": False, "delay_seconds": 90}
        )
        self.assertTrue(responses[3]["result"]["run_options"]["mute_enabled"])
        self.assertFalse(responses[3]["result"]["daily_enabled"])
        self.assertIsInstance(responses[3]["result"]["shutdown_supported"], bool)
        self.assertEqual(
            set(responses[3]["result"]),
            {"startup", "daily_enabled", "run_options", "shutdown_supported"},
        )
        self.assertEqual(
            json.loads(responses[4]["result"]["input"])["script_names"], ["ok-ww"]
        )
        self.assertFalse(self.root.joinpath("config/today.yml").exists())
        self.assertEqual(responses[3]["result"]["run_options"]["auth_code"], "")

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

    def test_resource_targets_resolve_without_gui_or_native_writes(self):
        before = self.native.read_bytes()
        result, responses = self.serve(
            [
                request(
                    "script.target", {"script_name": "ok-ww", "target": "folder"}, 1
                ),
                request(
                    "script.target", {"script_name": "ok-ww", "target": "github"}, 2
                ),
                request(
                    "script.target", {"script_name": "missing", "target": "log"}, 3
                ),
                request("script.target", {"script_name": "ok-ww", "target": "game"}, 4),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            responses[0]["result"],
            {"kind": "path", "value": str(self.root / "scripts")},
        )
        self.assertEqual(responses[1]["result"]["kind"], "url")
        self.assertTrue(
            responses[1]["result"]["value"].startswith("https://github.com/")
        )
        self.assertEqual(responses[2]["result"]["kind"], "unavailable")
        self.assertEqual(responses[3]["error"]["code"], -32002)
        self.assertFalse(responses[3]["error"]["data"]["refresh_required"])
        self.assertEqual(self.native.read_bytes(), before)

    def test_script_edit_round_trip_rename_and_validation_without_qt(self):
        result, responses = self.serve(
            [request("script.edit_view", {"script_name": "自定义脚本"})]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        view = responses[0]["result"]
        self.assertEqual(view["switches"], [])
        self.assertEqual(len(view["weekly_timeouts"]), 7)
        before = self.native.read_bytes()
        patch = {
            "script_path": "scripts/custom.py",
            "script_type": "python",
            "script_arguments": "--中文",
            "check_done": "script_closed",
            "game_process_name": "",
            "game_path": "",
            "kill_script_after_done": True,
            "kill_game_after_done": True,
            "block": False,
        }
        params = {
            "script_name": "自定义脚本",
            "display_name": "新的名字",
            "config_patch": patch,
            "weekly_timeouts": [None, 0, 60, 60, 60, 60, 86400],
            "switches": {},
        }
        result, responses = self.serve(
            [
                request(
                    "script.edit_save", {**params, "weekly_timeouts": [True] * 7}, 1
                ),
                request("script.edit_save", params, 2),
                request("script.edit_view", {"script_name": "新的名字"}, 3),
                request("script.edit_view", {"script_name": "自定义脚本"}, 4),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(responses[0]["error"]["code"], -32602)
        self.assertNotIn("data", responses[0]["error"])
        self.assertEqual(responses[1]["result"], {"script_name": "新的名字"})
        saved = responses[2]["result"]
        self.assertEqual(saved["script"]["script_arguments"], "--中文")
        self.assertFalse(saved["script"]["kill_game_after_done"])
        self.assertFalse(saved["script"]["block"])
        self.assertEqual(saved["weekly_timeouts"][1:], [0, 60, 60, 60, 60, 86400])
        self.assertEqual(responses[3]["error"]["code"], -32602)
        self.assertEqual(self.native.read_bytes(), before)
        config = load_yaml(str(self.root / "config/config.yml"))
        self.assertEqual(config["script_list"][1]["display_name"], "新的名字")

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

    def test_prepare_batch_saves_options_without_starting_a_run(self):
        result, responses = self.serve(
            [request("run.view", {"script_names": ["ok-ww"]})]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        options = responses[0]["result"]["options"]
        options.update(
            mute_enabled=True,
            close_running_enabled=False,
            rerun_enabled=True,
            shutdown_enabled=False,
        )
        result, responses = self.serve(
            [
                request(
                    "run.prepare",
                    {
                        "script_names": ["ok-ww"],
                        "options": options,
                        "confirm_invalid": True,
                    },
                    1,
                ),
                request("run.view", {"script_names": ["ok-ww"]}, 2),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("result", responses[0], responses[0])
        target = responses[0]["result"]
        self.assertEqual(target["args"], ["-m", "src.headless", "run"])
        self.assertEqual(json.loads(target["input"])["script_names"], ["ok-ww"])
        saved = responses[1]["result"]["options"]
        self.assertTrue(saved["mute_enabled"])
        self.assertFalse(saved["close_running_enabled"])
        self.assertTrue(saved["rerun_enabled"])
        self.assertEqual(saved["auth_code"], "")
        self.assertFalse((self.root / "config/script_chain").exists())

    def test_independent_worker_keeps_lease_without_importing_qt(self):
        result, responses = self.serve(
            [request("run.view", {"script_names": ["ok-ww"]})]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        command = self.command("run")
        command[2] = command[2].replace(
            "with patch('src.utils.get_root_dir', return_value=root):",
            """
def record(keys, target, **kwargs):
    import json
    import os
    from pathlib import Path
    from src.update.runtime import FileLease, UpdateBusyError
    from src.utils.utils_shutdown import _confirm_shutdown, RUST_CONFIRM_ENV
    from unittest.mock import Mock
    with patch.dict(os.environ, {RUST_CONFIRM_ENV: 'fake-rust.exe'}), patch('src.utils.utils_shutdown.rust_shutdown_supported', return_value=True), patch('src.utils.utils_shutdown.subprocess.run', return_value=Mock(returncode=42)) as confirm:
        assert _confirm_shutdown(45)
        assert confirm.call_args.args[0] == ['fake-rust.exe', '--shutdown-confirm', '45']
    try:
        with FileLease(Path(root)/'.update/runtime.lock'):
            locked=False
    except UpdateBusyError:
        locked=True
    Path(root,'worker.json').write_text(json.dumps({'keys':sorted(keys),'target':target,'locked':locked,'options':kwargs}),encoding='utf-8')

with patch('src.utils.get_root_dir', return_value=root), patch('src.service.chain_service.schedule_run', side_effect=record):
""",
        )
        options = responses[0]["result"]["options"]
        options.update(
            close_running_enabled=False, shutdown_enabled=False, notify_enabled=False
        )
        child = subprocess.run(
            command,
            input=json.dumps({"script_names": ["ok-ww"], "options": options}),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=self.env,
            timeout=30,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        recorded = json.loads((self.root / "worker.json").read_text(encoding="utf-8"))
        self.assertEqual(recorded["keys"], ["ok-ww"])
        self.assertEqual(recorded["target"], "now")
        self.assertTrue(recorded["locked"])
        self.assertFalse(recorded["options"]["close_running"])
        with FileLease(self.root / ".update/runtime.lock"):
            self.assertTrue((self.root / "worker.json").is_file())

    def test_launch_queries_return_distinct_targets_without_qt_or_execution(self):
        example = self.root / "config/config.example.yml"
        example.write_text(
            example.read_text(encoding="utf-8")
            + "  script_type: python\n  game_path: scripts/ok-ww.exe\n",
            encoding="utf-8",
        )
        result, responses = self.serve(
            [
                request(
                    "script.launch_target",
                    {"script_name": "ok-ww", "target": "script"},
                    1,
                ),
                request(
                    "script.launch_target",
                    {"script_name": "自定义脚本", "target": "script"},
                    2,
                ),
                request(
                    "script.launch_target",
                    {"script_name": "自定义脚本", "target": "game"},
                    3,
                ),
                request(
                    "script.launch_target",
                    {"script_name": "missing", "target": "script"},
                    4,
                ),
                request(
                    "script.launch_target",
                    {"script_name": "ok-ww", "target": "invalid"},
                    5,
                ),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            responses[0]["result"],
            {"kind": "association", "path": str(self.root / "scripts/ok-ww.exe")},
        )
        command = responses[1]["result"]
        self.assertEqual(command["kind"], "command")
        self.assertTrue(Path(command["program"]).is_absolute())
        self.assertEqual(
            command["args"],
            [
                str(self.root / "runner/launcher.py"),
                "--script",
                str(self.root / "scripts/custom.py"),
            ],
        )
        self.assertEqual(command["env"], {})
        self.assertEqual(responses[2]["result"], responses[0]["result"])
        self.assertEqual(responses[3]["result"]["kind"], "unavailable")
        self.assertFalse(responses[4]["error"]["data"]["refresh_required"])

    def test_list_add_reorder_remove_without_running_script_or_qt(self):
        added = self.root / "scripts/new.py"
        added.write_text(
            "from pathlib import Path\nPath(__file__).with_suffix('.started').touch()\n",
            encoding="utf-8",
        )
        result, responses = self.serve(
            [
                request("script.add", {"file_path": str(added)}, 1),
                request(
                    "script.reorder",
                    {"script_names": ["new", "ok-ww", "自定义脚本"]},
                    2,
                ),
                request("app.snapshot", request_id=3),
                request("script.reorder", {"script_names": ["ok-ww", "自定义脚本"]}, 4),
                request(
                    "script.add", {"file_path": str(self.root / "scripts/ok-ww.exe")}, 5
                ),
                request("script.remove", {"script_name": "ok-ww"}, 6),
                request("script.remove", {"script_name": "自定义脚本"}, 7),
                request("script.remove", {"script_name": "new"}, 8),
                request("app.snapshot", request_id=9),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            responses[0]["result"], {"script_name": "new", "display_name": "new"}
        )
        self.assertIsNone(responses[1]["result"])
        self.assertEqual(
            [script["script_name"] for script in responses[2]["result"]["scripts"]],
            ["new", "ok-ww", "自定义脚本"],
        )
        for index in (3, 7):
            self.assertEqual(responses[index]["error"]["code"], -32602)
            self.assertNotIn("data", responses[index]["error"])
        self.assertEqual(responses[4]["error"]["code"], -32001)
        self.assertFalse(responses[4]["error"]["data"]["refresh_required"])
        self.assertIsNone(responses[5]["result"])
        self.assertIsNone(responses[6]["result"])
        self.assertEqual(
            [script["script_name"] for script in responses[8]["result"]["scripts"]],
            ["new"],
        )
        self.assertFalse(added.with_suffix(".started").exists())
        self.assertTrue((self.root / "scripts/custom.py").exists())
        weekly = load_yaml(str(self.root / "config/weekly.yml"))
        self.assertNotIn("ok-ww", weekly["weekly_timeouts"])
        self.assertNotIn("自定义脚本", weekly["weekly_timeouts"])
        self.assertIn("new", weekly["weekly_timeouts"])

    def test_icon_paths_are_read_only_without_gui_imports(self):
        from src.utils.utils_yaml import dump_yaml

        result, _ = self.serve([request("app.snapshot")])
        self.assertEqual(result.returncode, 0, result.stderr)
        config_path = self.root / "config/config.yml"
        config = load_yaml(str(config_path))
        config["script_list"][0]["game_path"] = str(self.root / "游戏.exe")
        config["script_list"][0]["script_type"] = "external"
        dump_yaml(str(config_path), config)
        before = config_path.read_bytes()
        result, responses = self.serve(
            [
                request("app.snapshot"),
                request("script.icon_path", {"script_name": "ok-ww"}, 2),
                request("script.icon_path", {"script_name": "removed"}, 3),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = responses[0]["result"]
        self.assertEqual(
            Path(snapshot["scripts"][0]["icon_path"]),
            self.root / "scripts/ok-ww.exe",
        )
        self.assertEqual(
            snapshot["scripts"][1]["icon_path"], snapshot["default_icon_path"]
        )
        self.assertEqual(responses[1]["result"]["path"], str(self.root / "游戏.exe"))
        self.assertIsNone(responses[2]["result"]["path"])
        self.assertEqual(config_path.read_bytes(), before)

    def test_wallpaper_set_read_reset_without_qt(self):
        picture = self.root / "中文壁纸.png"
        picture.write_bytes(b"source fixture")
        result, responses = self.serve(
            [
                request(
                    "wallpaper.set",
                    {"script_name": "自定义脚本", "file_path": str(picture)},
                    1,
                ),
                request("wallpaper.view", {"script_name": "自定义脚本"}, 2),
                request(
                    "wallpaper.set", {"script_name": "自定义脚本", "file_path": None}, 3
                ),
                request("wallpaper.current", {"script_name": "自定义脚本"}, 4),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(responses[0]["result"])
        self.assertEqual(responses[1]["result"]["source"], str(picture))
        self.assertEqual(responses[1]["result"]["mode"], "image")
        self.assertIsNone(responses[2]["result"])
        self.assertIsNone(responses[3]["result"]["custom_path"])
        self.assertEqual(picture.read_bytes(), b"source fixture")

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
                            daily_name="培养目标",
                            task_name="培养目标",
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


class RunRequestTests(unittest.TestCase):
    def setUp(self):
        self.service = AppService(frontend="rust")
        self.addCleanup(self.service.close)
        self.enterContext(
            patch("src.service.chain_service.selected_scripts", return_value=[])
        )
        self.invalid = self.enterContext(
            patch.object(self.service, "collect_invalid_scripts", return_value=[])
        )

    def test_saved_run_returns_target_without_saving_or_starting(self):
        options = RunOptions(mute_enabled=True, close_running_enabled=False)
        with (
            patch.object(self.service, "load_run_options", return_value=options),
            patch.object(self.service, "apply_run_options") as save,
            patch("src.service.chain_service.schedule_run") as run,
        ):
            response = handle_request(
                self.service, request("run.saved", {"script_names": ["test"]})
            )
        save.assert_not_called()
        run.assert_not_called()
        self.invalid.assert_not_called()
        target = response["result"]
        self.assertEqual(target["args"][-1], "run")
        self.assertEqual(
            json.loads(target["input"]),
            {"script_names": ["test"], "options": asdict(options)},
        )

    def test_invalid_script_warning_requires_confirmation(self):
        self.invalid.return_value = [("demo", "missing")]
        for confirmed in (False, 1):
            with (
                self.subTest(confirmed=confirmed),
                patch.object(self.service, "apply_run_options") as save,
            ):
                response = handle_request(
                    self.service,
                    request(
                        "run.prepare",
                        {
                            "script_names": ["demo"],
                            "options": asdict(RunOptions()),
                            "confirm_invalid": confirmed,
                        },
                    ),
                )
                self.assertEqual(response["error"]["code"], -32602)
                save.assert_not_called()

    def test_prepare_passes_names_in_stdin_and_omits_credentials(self):
        from src.utils.utils_shutdown import RUST_CONFIRM_ENV

        names = ["中文,逗号 & 空格"]
        options = RunOptions(
            email="test@example.invalid",
            auth_code="test-secret",
            mute_enabled=True,
            shutdown_enabled=True,
            shutdown_delay=45,
        )
        saved = RunOptions(
            email=options.email,
            mute_enabled=True,
            shutdown_enabled=True,
            shutdown_delay=45,
        )
        with (
            patch.object(self.service, "apply_run_options") as save,
            patch.object(self.service, "load_run_options", return_value=saved),
            patch(
                "src.utils.utils_shutdown.rust_shutdown_supported", return_value=True
            ),
            patch.dict(os.environ, {RUST_CONFIRM_ENV: "/fake/gui"}),
        ):
            response = handle_request(
                self.service,
                request(
                    "run.prepare",
                    {
                        "script_names": names,
                        "options": asdict(options),
                        "confirm_invalid": False,
                    },
                ),
            )
            view = handle_request(
                self.service, request("run.view", {"script_names": names})
            )
        save.assert_called_once_with(options)
        target = response["result"]
        self.assertEqual(target["args"][-1], "run")
        self.assertTrue(target["console"])
        self.assertEqual(target["env"], {RUST_CONFIRM_ENV: "/fake/gui"})
        self.assertTrue(view["result"]["shutdown_supported"])
        self.assertEqual(
            json.loads(target["input"]),
            {"script_names": names, "options": asdict(saved)},
        )
        self.assertNotIn("test-secret", json.dumps(target))
        self.assertNotIn(names[0], target["args"])

    def test_failed_save_returns_no_launch_target(self):
        with (
            patch.object(
                self.service, "apply_run_options", side_effect=OSError("disk full")
            ),
            patch.object(self.service, "load_run_options") as read,
            self.assertLogs("src.headless", level="ERROR"),
        ):
            response = handle_request(
                self.service,
                request(
                    "run.prepare",
                    {
                        "script_names": ["demo"],
                        "options": asdict(RunOptions()),
                        "confirm_invalid": False,
                    },
                ),
            )
        read.assert_not_called()
        self.assertNotIn("result", response)
        self.assertEqual(response["error"]["code"], -32002)
        self.assertTrue(response["error"]["data"]["refresh_required"])


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

    def test_read_failure_does_not_require_refresh(self):
        service = mock_service()
        service.script_view.side_effect = OSError("query failed")
        with self.assertLogs("src.headless", level="ERROR"):
            response = handle_request(
                service, request("script.view", {"script_name": "脚本"})
            )
        self.assertEqual(response["error"]["code"], -32002)
        self.assertFalse(response["error"]["data"]["refresh_required"])

    def test_each_batch_method_checks_busy_state_after_previous_call(self):
        service = mock_service()

        def backup():
            service.jobs.running = True
            return {"id": "backup"}

        service.start_backup.side_effect = backup
        service.poll_job.return_value = {"state": "running"}
        responses = handle_request(
            service,
            [
                request("backup.start"),
                request("script.remove", {"script_name": "test"}, request_id=2),
                request("job.poll", {"job_id": "backup"}, request_id=3),
            ],
        )
        self.assertEqual(responses[0]["result"], {"id": "backup"})
        self.assertEqual(responses[1]["error"]["code"], -32003)
        self.assertEqual(responses[2]["result"], {"state": "running"})
        service.remove_script.assert_not_called()

    def test_invalid_startup_settings_never_save(self):
        service = mock_service()
        for value in (
            None,
            {},
            {"enabled": 1, "delay_seconds": 60},
            {"enabled": True, "delay_seconds": True},
            {"enabled": True, "delay_seconds": 0},
            {"enabled": False, "delay_seconds": 3601},
            {"enabled": False, "delay_seconds": 60, "unknown": True},
        ):
            with self.subTest(value=value):
                response = handle_request(
                    service, request("settings.startup_save", {"options": value})
                )
                self.assertEqual(response["error"]["code"], -32602)
        service.apply_startup_options.assert_not_called()

    def test_settings_save_converts_options_without_starting(self):
        startup = StartupOptions(False, 120)
        options = RunOptions(mute_enabled=True, close_running_enabled=False)
        service = mock_service()
        service.apply_startup_options.return_value = None
        service.apply_run_options.return_value = None
        for method, value in (
            ("settings.startup_save", startup),
            ("settings.run_save", options),
        ):
            with self.subTest(method=method):
                response = handle_request(
                    service, request(method, {"options": asdict(value)})
                )
                self.assertIsNone(response["result"])
        self.assertEqual(
            service.mock_calls,
            [call.apply_startup_options(startup), call.apply_run_options(options)],
        )

    def test_invalid_run_settings_never_save(self):
        service = mock_service()
        for change in (
            {"mute_enabled": 1},
            {"shutdown_delay": True},
            {"shutdown_delay": 86401},
            {"smtp_port": "bad"},
            {"smtp_port": "65536"},
            {"auth_code": "test-secret"},
            {"unknown": 1},
        ):
            with self.subTest(change=change):
                response = handle_request(
                    service,
                    request(
                        "settings.run_save",
                        {"options": {**asdict(RunOptions()), **change}},
                    ),
                )
                self.assertEqual(response["error"]["code"], -32602)
        service.apply_run_options.assert_not_called()

    def test_shutdown_without_frontend_rejected_at_boundary(self):
        with (
            patch(
                "src.utils.utils_shutdown.rust_shutdown_supported", return_value=False
            ),
            self.assertRaisesRegex(InvalidParams, "关机确认入口"),
        ):
            _parse_run_options(
                asdict(RunOptions(shutdown_enabled=True, shutdown_delay=45))
            )

    def test_daily_validation_before_registration_and_pause_preserves_options(self):
        plan = DailyPlanOptions(
            False, "04:10", RunOptions(shutdown_enabled=True, shutdown_delay=45)
        )
        service = mock_service()
        service.apply_daily_plan.return_value = None
        with (
            patch("src.headless._daily_task") as task,
            patch(
                "src.utils.utils_shutdown.rust_shutdown_supported", return_value=False
            ),
        ):
            for values in (
                None,
                {},
                {**asdict(plan), "enabled": 1},
                {**asdict(plan), "target_time": "25:00"},
                {**asdict(plan), "target_time": "bad"},
                {**asdict(plan), "unknown": True},
                {**asdict(plan), "run_options": []},
                {
                    **asdict(plan),
                    "run_options": {**asdict(plan.run_options), "shutdown_delay": -1},
                },
            ):
                with self.subTest(values=values):
                    response = handle_request(
                        service, request("plan.save", {"plan": values})
                    )
                    self.assertEqual(response["error"]["code"], -32602)
            service.apply_daily_plan.assert_not_called()
            task.assert_not_called()
            response = handle_request(
                service, request("plan.save", {"plan": asdict(plan)})
            )
        service.apply_daily_plan.assert_called_once_with(plan, task=task.return_value)
        self.assertIsNone(response["result"])

    def test_daily_enable_without_frontend_does_not_register(self):
        service = mock_service()
        with (
            patch("src.headless._daily_task") as task,
            patch(
                "src.utils.utils_shutdown.rust_shutdown_supported", return_value=False
            ),
        ):
            response = handle_request(
                service, request("plan.save", {"plan": asdict(DailyPlanOptions(True))})
            )
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("Windows Rust 前端", response["error"]["message"])
        service.apply_daily_plan.assert_not_called()
        task.assert_not_called()

    def test_daily_entry_uses_headless_and_frontend_without_config_snapshot(self):
        from src.utils.utils_shutdown import RUST_CONFIRM_ENV

        for frozen, prefix in ((False, ["-m", "src.headless"]), (True, [])):
            with (
                self.subTest(frozen=frozen),
                patch.dict(os.environ, {RUST_CONFIRM_ENV: "/中文 gui.exe"}),
                patch("sys.frozen", frozen, create=True),
                patch("src.service.daily_plan.WindowsDailyTask") as task,
            ):
                _daily_task()
            task.assert_called_once_with(
                entry=(
                    sys.executable,
                    [*prefix, "daily", "--shutdown-ui", "/中文 gui.exe"],
                )
            )

    def test_script_edit_converts_at_boundary_and_preserves_response(self):
        params = {
            "script_name": "旧名",
            "display_name": "新名",
            "config_patch": {"script_path": "scripts/custom.py"},
            "weekly_timeouts": [None] * 7,
            "switches": {"任务": False},
        }
        service = mock_service()
        service.update_script.return_value = "新名"
        response = handle_request(service, request("script.edit_save", params))
        service.update_script.assert_called_once_with(ScriptEdit(**params))
        self.assertEqual(
            response,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"script_name": "新名"},
            },
        )

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


class HeadlessEntryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.fixture = HeadlessFixture(self.root)
        self.env = {**os.environ, "TMPDIR": str(self.root), "TEMP": str(self.root)}

    def run_entry(self, *args):
        command = self.fixture.command(*args)
        return subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    def test_legacy_outputs_and_utf8_arguments_without_gui(self):
        for arguments, code, expected in (
            (("--selftest",), 0, {"status": "ok"}),
            (("--list-scripts",), 0, {"scripts": ["ok-ww", "自定义脚本"]}),
            (("--get-script", "自定义脚本"), 0, {"status": "ok"}),
            (("--get-script", "不存在"), 1, {"status": "not_found"}),
        ):
            with self.subTest(arguments=arguments):
                output = self.root / "中文 结果.json"
                result = self.run_entry(*arguments, "--out", str(output))
                self.assertEqual(result.returncode, code, result.stderr)
                data = json.loads(output.read_text(encoding="utf-8"))
                for key, value in expected.items():
                    self.assertEqual(data[key], value)
        (self.root / "version.json").write_text(
            '{"version":"1.2.3","frontend":"rust"}', encoding="utf-8"
        )
        result = self.run_entry("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1.2.3", (self.root / "odh_gui_version.txt").read_text())

    def test_invalid_or_missing_action_cannot_fall_back_to_gui(self):
        for args in ((), ("--unknown-option",), ("--out", "unused.json")):
            with self.subTest(args=args):
                result = self.run_entry(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn("CLI 加载了 GUI", result.stderr)

    def test_legacy_update_gate_precedes_configuration(self):
        with FileLease(self.root / ".update/intent.lock"):
            result = self.run_entry("--selftest", "--out", str(self.root / "out.json"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse((self.root / "config/config.yml").exists())
        self.assertFalse((self.root / "out.json").exists())

    def test_frozen_entry_uses_sibling_shutdown_ui_and_preserves_rpc(self):
        with (
            patch("src.headless._run_command", return_value=7) as entry,
            patch("sys.frozen", True, create=True),
            patch("sys.executable", str(self.root / "OneDragon-Helper-CLI.exe")),
            patch.dict(os.environ),
        ):
            os.environ.pop(RUST_CONFIRM_ENV, None)
            self.assertEqual(main(["serve", "--stdio"]), 7)
            self.assertEqual(entry.call_args.args[0].command, "serve")
            self.assertTrue(entry.call_args.args[0].stdio)
            self.assertEqual(
                os.environ[RUST_CONFIRM_ENV], str(self.root / "OneDragon-Helper.exe")
            )
            os.environ[RUST_CONFIRM_ENV] = "explicit-parent.exe"
            self.assertEqual(main(["--selftest"]), 7)
            self.assertEqual(entry.call_args.args[0].command, "legacy")
            self.assertEqual(entry.call_args.args[0].arguments, ["--", "--selftest"])
            self.assertEqual(os.environ[RUST_CONFIRM_ENV], "explicit-parent.exe")

    def test_headless_selects_rust_update_service(self):
        from argparse import Namespace
        from contextlib import nullcontext

        from src.headless import _run_command

        with (
            patch("src.update.runtime.application_lease", return_value=nullcontext()),
            patch("src.config.generate_config.config_workflow"),
            patch("src.utils.utils_logger.setup_logging"),
            patch("src.utils.utils_logger.install_crash_hooks"),
            patch("src.service.app_service.AppService") as factory,
            patch("src.headless._call", return_value=0) as dispatch,
        ):
            self.assertEqual(
                _run_command(Namespace(command="call", method="update.view")), 0
            )
        factory.assert_called_once_with(frontend="rust")
        dispatch.assert_called_once_with(factory.return_value, "update.view")
