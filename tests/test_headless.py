"""独立进程验证无 Qt CLI；主配置与游戏配置均在临时目录。"""

import json
import os
import queue
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, call

from src.headless import handle_request
from src.update.runtime import FileLease, UpdateBusyError
from src.utils.utils_yaml import load_yaml
from tests.support.headless import PROJECT_ROOT, HeadlessFixture


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

    def test_daily_plan_cli_and_independent_entry_without_qt(self):
        from dataclasses import asdict

        from src.service.daily_plan import DailyPlanOptions
        from src.service.schedule import RunOptions

        plan = DailyPlanOptions(
            True, "09:20", RunOptions(mute_enabled=True, close_running_enabled=False)
        )
        command = self.command("serve", "--stdio")
        command[2] = command[2].replace(
            "with patch('src.utils.get_root_dir', return_value=root):",
            """
with patch('src.utils.get_root_dir', return_value=root), patch('src.service.daily_cli.rust_shutdown_supported', return_value=True), patch('src.service.daily_cli._task') as task:
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
        from dataclasses import asdict

        from src.service.schedule import RunOptions

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
        self.assertEqual(responses[3]["error"]["code"], "operation_failed")
        self.assertFalse(responses[3]["error"]["refresh_required"])
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
        self.assertEqual(responses[0]["error"]["code"], "invalid_params")
        self.assertFalse(responses[0]["error"]["refresh_required"])
        self.assertEqual(responses[1]["result"], {"script_name": "新的名字"})
        saved = responses[2]["result"]
        self.assertEqual(saved["script"]["script_arguments"], "--中文")
        self.assertFalse(saved["script"]["kill_game_after_done"])
        self.assertFalse(saved["script"]["block"])
        self.assertEqual(saved["weekly_timeouts"][1:], [0, 60, 60, 60, 60, 86400])
        self.assertEqual(responses[3]["error"]["code"], "invalid_params")
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
            self.assertEqual(response["error"]["code"], "operation_failed", response)
            self.assertTrue(response["error"]["refresh_required"])
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

with patch('src.utils.get_root_dir', return_value=root), patch('src.service.run_service.chain_service.schedule_run', side_effect=record):
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
                "-m",
                "src.runner.launcher",
                "--script",
                str(self.root / "scripts/custom.py"),
            ],
        )
        self.assertEqual(set(command["env"]), {"PYTHONPATH"})
        self.assertEqual(responses[2]["result"], responses[0]["result"])
        self.assertEqual(responses[3]["result"]["kind"], "unavailable")
        self.assertFalse(responses[4]["error"]["refresh_required"])

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
        self.assertEqual(responses[0]["result"], {"script_name": "new"})
        self.assertIsNone(responses[1]["result"])
        self.assertEqual(
            [script["script_name"] for script in responses[2]["result"]["scripts"]],
            ["new", "ok-ww", "自定义脚本"],
        )
        for index in (3, 7):
            self.assertEqual(responses[index]["error"]["code"], "invalid_params")
            self.assertFalse(responses[index]["error"]["refresh_required"])
        self.assertEqual(responses[4]["error"]["code"], "duplicate_script")
        self.assertFalse(responses[4]["error"]["refresh_required"])
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
            [
                {"protocol_version": 1, "id": i, "result": None}
                for i in range(len(cases))
            ],
        )
        self.assertEqual(before, self.native.read_bytes())

    def test_call_accepts_static_sequence_display_name(self):
        result, responses = self.run_cli(
            ["call", "daily.select"],
            json.dumps(selection(sequence="梦州-迅刀"), ensure_ascii=False),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(responses, [{"protocol_version": 1, "id": 1, "result": None}])
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
            self.assertEqual(responses[i]["error"]["code"], "operation_failed")
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
        self.assertEqual(responses[1]["error"]["code"], "operation_failed")
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
            self.assertEqual(response["error"]["code"], "operation_failed")
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
            (request("script.view"), "invalid_params"),
            (request("daily.select", {"task_name": "材料"}), "invalid_params"),
            (request("daily.select", selection(extra=True)), "invalid_params"),
        ]
        service = Mock()
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
                service = Mock()
                getattr(service, attribute).return_value = None
                service.script_view.side_effect = OSError("查询失败")
                response = handle_request(service, request(method, params))
                self.assertEqual(
                    response, {"protocol_version": 1, "id": 1, "result": None}
                )
                self.assertEqual(
                    service.mock_calls, [getattr(call, attribute)(**params)]
                )
                self.assertEqual(
                    json.dumps(getattr(service, attribute).call_args.kwargs),
                    json.dumps(params),
                )

    def test_failure_after_write_does_not_claim_rollback(self):
        service = Mock()
        service.select_daily.side_effect = OSError("second write failed")
        with self.assertLogs("src.headless", level="ERROR") as logs:
            response = handle_request(service, request("daily.select", selection()))
        self.assertTrue(response["error"]["refresh_required"])
        self.assertIn("OSError", "".join(logs.output))
        service.select_daily.assert_called_once_with(**selection())
