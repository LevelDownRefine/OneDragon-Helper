"""真实管道与 Qt 事件循环验证异步客户端，所有子进程均为临时测试程序。"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal

from gui.cli_client import CliClient, CliFailure, CliSession
from gui.controllers.cli_task_card import CliTaskCardController, valid_script_view
from tests.gui.helpers import get_app

CHILD = """
import json, sys, time
for line in sys.stdin:
    request = json.loads(line)
    method = request['method']
    if method == 'hang':
        time.sleep(10)
    if method == 'exit':
        sys.exit(2)
    sys.stderr.write('diagnostic' * 10000)
    sys.stderr.flush()
    response = {'jsonrpc': '2.0', 'id': request['id'], 'result': request['params']}
    if method == 'null':
        response['result'] = None
    if method == 'wrong-id':
        response['id'] += 1
    if method == 'error':
        response.pop('result')
        response['error'] = {'code': -32002, 'message': 'partial write',
                             'data': {'refresh_required': True}}
    data = (json.dumps(response, ensure_ascii=False) + '\\n').encode('utf-8')
    sys.stdout.buffer.write(data[:3]); sys.stdout.buffer.flush()
    sys.stdout.buffer.write(data[3:]); sys.stdout.buffer.flush()
"""


class CliClientTests(unittest.TestCase):
    def setUp(self):
        get_app()
        self.temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.script = Path(self.temporary) / "child.py"
        self.script.write_text(CHILD, encoding="utf-8")
        self.client = CliClient(
            sys.executable, [str(self.script)], self.temporary, timeout_ms=500
        )
        self.results = []
        self.errors = []
        self.client.succeeded.connect(lambda *args: self.results.append(args))
        self.client.failed.connect(lambda *args: self.errors.append(args))
        self.addCleanup(self.close_client)

    def wait_for(self, predicate, timeout_ms=5000):
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(5)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        poll.start()
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        deadline.start(timeout_ms)
        if not predicate():
            loop.exec()
        self.assertTrue(predicate(), (self.results, self.errors))

    def close_client(self):
        self.client.close()
        self.wait_for(lambda: not self.client.running)

    def test_protected_timeout_sends_eof_and_waits_for_backend_cleanup(self):
        self.script.write_text(
            "import sys,time,pathlib\n"
            "sys.stdin.readline()\n"
            "time.sleep(2.2)\n"
            "sys.stdin.read()\n"
            "pathlib.Path('completed').write_text('done')\n",
            encoding="utf-8",
        )
        session = CliSession(self.client, None)
        self.assertTrue(session.hold())
        self.client.request("restore.start", {})
        self.wait_for(lambda: bool(self.errors))
        self.assertTrue(session.busy)
        self.assertTrue(self.client.running)
        session.retire()
        self.assertTrue(session.busy)
        self.wait_for(lambda: not self.client.running)
        self.assertEqual((Path(self.temporary) / "completed").read_text(), "done")
        self.assertFalse(session.busy)

    def test_queue_utf8_fragmented_response_null_and_rpc_error(self):
        first = self.client.request("echo", {"文案": "中文"})
        second = self.client.request("null")
        third = self.client.request("error")
        fourth = self.client.request("echo", {"after": True})
        self.wait_for(lambda: len(self.results) + len(self.errors) == 4)
        self.assertEqual(
            self.results,
            [(first, {"文案": "中文"}), (second, None), (fourth, {"after": True})],
        )
        self.assertEqual(self.errors, [(third, CliFailure(-32002, "partial write"))])

    def test_result_can_open_modal_loop_and_submit_next_request(self):
        completed = []

        def received(request_id, result):
            if request_id != 1:
                return
            loop = QEventLoop()
            self.client.succeeded.connect(lambda _id, _result: loop.quit())
            self.client.request("echo", {"saved": True})
            QTimer.singleShot(1500, loop.quit)
            loop.exec()
            completed.append(len(self.results))

        self.client.succeeded.connect(received)
        self.client.request("echo", {"open": True})
        self.wait_for(lambda: bool(completed))
        self.assertEqual(completed, [2])
        self.assertEqual(self.errors, [])

    def assert_transport_failure(self, method):
        first = self.client.request(method)
        second = self.client.request("echo")
        self.wait_for(lambda: len(self.errors) == 2)
        self.assertEqual([row[0] for row in self.errors], [first, second])
        self.assertTrue(all(row[1].code == "transport_failed" for row in self.errors))
        self.assertEqual(self.results, [])
        with self.assertRaises(RuntimeError):
            self.client.request("echo")

    def test_wrong_id_breaks_session_without_replay(self):
        self.assert_transport_failure("wrong-id")

    def test_process_exit_fails_active_and_queued(self):
        self.assert_transport_failure("exit")

    def test_timeout_fails_active_and_queued(self):
        self.assert_transport_failure("hang")

    def test_close_drains_queue_then_eof(self):
        first = self.client.request("echo", {"saved": True})
        self.client.close()
        self.wait_for(lambda: len(self.results) == 1 and not self.client.running)
        self.assertEqual(self.results, [(first, {"saved": True})])
        self.assertEqual(self.errors, [])

    def test_real_headless_session_uses_same_protocol_without_gui_imports(self):
        project = Path(__file__).resolve().parents[3]
        config = Path(self.temporary) / "config"
        config.mkdir()
        for source in (project / "config").iterdir():
            if source.is_file() and source.suffix in {".yml", ".json"}:
                shutil.copyfile(source, config / source.name)
        (config / "config.example.yml").write_text(
            "script_list:\n- display_name: 自定义\n  script_path: custom.py\n",
            encoding="utf-8",
        )
        (Path(self.temporary) / "custom.py").touch()
        self.script.write_text(
            "import sys, runpy, importlib.abc\n"
            "from unittest.mock import patch\n"
            f"sys.path.insert(0, {str(project / 'python-backend')!r})\n"
            "class NoGui(importlib.abc.MetaPathFinder):\n"
            "    def find_spec(self, fullname, path=None, target=None):\n"
            "        if fullname.startswith(('gui', 'PySide6', 'shiboken6')):\n"
            "            raise AssertionError(fullname)\n"
            "sys.meta_path.insert(0, NoGui())\n"
            "sys.argv = ['headless', 'serve', '--stdio']\n"
            f"with patch('src.utils.get_root_dir', return_value={self.temporary!r}):\n"
            "    runpy.run_module('src.headless', run_name='__main__')\n",
            encoding="utf-8",
        )
        self.client._timer.setInterval(30000)
        first = self.client.request("app.snapshot")
        second = self.client.request("script.view", {"script_name": "自定义"})
        self.wait_for(
            lambda: len(self.results) + len(self.errors) == 2, timeout_ms=30000
        )
        self.assertEqual(self.errors, [])
        self.assertEqual(self.results[0][0], first)
        self.assertEqual(self.results[0][1]["scripts"][0]["display_name"], "自定义")
        self.assertEqual(self.results[1][0], second)
        self.assertEqual(self.results[1][1]["dailies"], [])
        self.assertEqual(self.results[1][1]["weeklies"], [])


class FakeClient(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, object)

    def __init__(self):
        super().__init__()
        self.requests = []
        self.usable = True

    def close(self):
        self.usable = False

    def request(self, method, params):
        self.requests.append((method, params))
        return len(self.requests)


class CliTaskCardTests(unittest.TestCase):
    def setUp(self):
        get_app()
        self.client = FakeClient()
        self.games = SimpleNamespace(
            current_game={"script_name": "A", "display_name": "A"}
        )
        self.messages = []
        self.card = CliTaskCardController(self.games, self.client, self.messages.append)

    def view(self, name):
        return {
            "script": {"script_name": name, "adapted": True},
            "dailies": [],
            "weeklies": [],
        }

    def test_switch_discards_old_response_including_a_b_a(self):
        self.card.refresh()
        self.games.current_game["script_name"] = "B"
        self.card.refresh()
        self.games.current_game["script_name"] = "A"
        self.card.refresh()
        self.client.succeeded.emit(1, self.view("old-A"))
        self.client.succeeded.emit(2, self.view("B"))
        self.assertFalse(self.card.task_adapted)
        self.client.succeeded.emit(3, self.view("A"))
        self.assertEqual(self.card._view["script"]["script_name"], "A")

    def test_write_success_and_partial_error_refresh_without_replay(self):
        self.card.selectDaily("daily", "task", 1)
        self.client.succeeded.emit(1, None)
        self.assertEqual(
            [row[0] for row in self.client.requests], ["daily.select", "script.view"]
        )
        self.client.failed.emit(2, CliFailure("transport_failed", "refresh failed"))
        self.assertEqual(len(self.client.requests), 2)
        self.card.selectWeeklyStart("weekly", 2)
        self.client.failed.emit(3, CliFailure(-32002, "partial"))
        self.assertEqual(
            [row[0] for row in self.client.requests],
            ["daily.select", "script.view", "weekly.start", "script.view"],
        )
        self.assertEqual(self.messages, ["refresh failed", "partial"])

    def test_protocol_records_are_presented_by_gui(self):
        self.card.refresh()
        view = self.view("A")
        values = [
            {
                "display_name": "副本",
                "physical_name": "dungeon",
                "options": {"values": [{"display_name": "线路", "physical_name": 1}]},
            }
        ]
        view["dailies"] = [
            {
                "name": "日常",
                "task": "副本",
                "sequence": 1,
                "enabled": False,
                "options": {"values": values},
            }
        ]
        view["weeklies"] = [
            {
                "name": "周常",
                "task": None,
                "start_day": 0,
                "options": {"values": values},
            }
        ]
        self.client.succeeded.emit(1, view)
        self.assertEqual(
            self.card.daily_items,
            [
                {
                    "name": "日常",
                    "task_label": "不启用",
                    "can_disable": True,
                    "disabled": True,
                }
            ],
        )
        self.assertEqual(self.card.daily_options("日常"), values)
        self.assertEqual(self.card.weekly_task_options("周常"), values)
        self.assertEqual(
            self.card.weekly_items,
            [
                {
                    "name": "周常",
                    "has_task": True,
                    "task_label": "选择副本",
                    "start_set": True,
                    "start_label": "不启用",
                }
            ],
        )
        view["dailies"][0]["enabled"] = True
        self.assertEqual(self.card.daily_items[0]["task_label"], "副本 · 线路")

    def test_refresh_replaces_failed_client_and_discards_old_signals_and_writes(self):
        replacement = FakeClient()
        self.card._client_factory = lambda: replacement
        self.card.selectDaily("daily", "task", 1)
        self.client.usable = False
        self.client.failed.emit(1, CliFailure("transport_failed", "failed"))
        self.card.refresh()
        self.assertIs(self.card._client, replacement)
        self.assertEqual(replacement.requests, [("script.view", {"script_name": "A"})])
        self.client.succeeded.emit(1, self.view("old"))
        self.client.failed.emit(1, CliFailure("transport_failed", "late exit"))
        self.assertIsNone(self.card._view)
        replacement.succeeded.emit(1, self.view("A"))
        self.assertTrue(self.card.task_adapted)
        self.assertEqual(self.messages, ["failed"])
        self.assertEqual(len(self.client.requests), 1)

    def test_malformed_views_clear_state_and_report_without_exceptions(self):
        valid = self.view("A")
        invalid = [
            None,
            [],
            {},
            {**valid, "script": None},
            self.view("wrong"),
            {**valid, "dailies": {}},
            {**valid, "dailies": [{"name": "daily"}]},
            {
                **valid,
                "weeklies": [
                    {"name": "weekly", "task": None, "options": None, "start_day": True}
                ],
            },
            {
                **valid,
                "weeklies": [
                    {"name": "weekly", "task": None, "options": None, "start_day": 8}
                ],
            },
        ]
        for response in invalid:
            with self.subTest(response=response):
                self.card.refresh()
                self.client.succeeded.emit(len(self.client.requests), response)
                self.assertIsNone(self.card._view)
                self.assertEqual(self.card.daily_items, [])
                self.assertEqual(self.card.weekly_items, [])
                self.assertEqual(self.messages[-1], "CLI 任务卡响应无效，请刷新")
                self.assertFalse(valid_script_view(response, "A"))

    def test_response_validation_remains_enabled_under_python_optimization(self):
        result = subprocess.run(
            [
                sys.executable,
                "-O",
                "-c",
                "from gui.controllers.cli_task_card import valid_script_view; "
                "raise SystemExit(1 if valid_script_view(None, 'A') else 0)",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_write_response_only_refreshes_and_does_not_replay(self):
        self.card.selectWeeklyStart("weekly", 1)
        self.client.succeeded.emit(1, {"unexpected": True})
        self.assertEqual(self.messages, ["CLI 写操作响应无效，请刷新"])
        self.assertEqual(
            [row[0] for row in self.client.requests], ["weekly.start", "script.view"]
        )

    def test_nested_options_and_nullable_fields_reject_invalid_types(self):
        for options in (
            {"values": {}},
            {"values": [{}]},
            {
                "values": [
                    {
                        "display_name": "task",
                        "physical_name": 1,
                        "options": {"values": None},
                    }
                ]
            },
        ):
            view = self.view("A")
            view["dailies"] = [
                {
                    "name": "daily",
                    "task": None,
                    "sequence": None,
                    "enabled": None,
                    "options": options,
                }
            ]
            self.assertFalse(valid_script_view(view, "A"))
