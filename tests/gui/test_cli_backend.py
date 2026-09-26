"""真实 Qt 事件循环 + CLI 子进程，验证任务卡闭环与异步故障。"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest

from src.gui.cli_client import CliClient
from src.gui.controllers.cli_task_card import CliTaskCardController
from src.gui.main_window import QmlBridge
from src.update.runtime import FileLease
from tests.gui.helpers import get_app
from tests.support.headless import PROJECT_ROOT, HeadlessFixture


class DeferredClient(QObject):
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.requests = []

    def request(self, method, params, callback):
        self.requests.append((method, params, callback))


class CliGuiTests(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.fixture = HeadlessFixture(self.root)

    def wait_for(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertTrue(predicate(), "等待 Qt/CLI 状态超时")

    def client(self, command=None, timeout_ms=10000):
        client = CliClient(
            command=command or self.fixture.command("serve", "--stdio"),
            timeout_ms=timeout_ms,
        )
        self.addCleanup(client.close)
        return client

    def test_bridge_reads_and_writes_through_real_cli(self):
        client = self.client()
        with (
            patch("src.gui.controllers.background.BackgroundController.apply_current"),
            patch(
                "src.gui.controllers.game_list.ScriptIconProvider._load_icon",
                return_value=QPixmap(1, 1),
            ),
            patch(
                "src.service.app_service.AppService.load_config",
                side_effect=AssertionError("GUI 绕过 CLI 读列表"),
            ),
            patch(
                "src.gui.controllers.task_card.get_daily_readback",
                side_effect=AssertionError("GUI 绕过 CLI 反读"),
            ),
            patch(
                "src.service.app_service.AppService.set_script_daily_task",
                side_effect=AssertionError("GUI 绕过 CLI 写日常"),
            ),
        ):
            bridge = QmlBridge(cli_backend=True, cli_client=client)
            self.addCleanup(bridge.close_cli)
            self.wait_for(lambda: bridge.taskStatus == "已同步")
            self.assertEqual(
                [game["script_name"] for game in bridge.games], ["ok-ww", "自定义脚本"]
            )
            self.assertEqual(
                bridge.task_card.daily_items[0]["task_label"], "模拟领域 · 贝币"
            )
            pid = client._process.processId()
            bridge.selectDaily("每日任务", "凝素领域", 1)
            self.assertTrue(bridge.taskBusy)
            self.wait_for(lambda: not bridge.taskBusy)
            self.assertIn("凝素领域", bridge.task_card.daily_items[0]["task_label"])
            native = json.loads(self.fixture.native.read_text(encoding="utf-8"))
            self.assertEqual(native["Which to Farm"], "Forgery Challenge")
            self.assertEqual(native["Which Forgery Challenge to Farm"], 1)
            self.assertEqual(native["untouched"], self.fixture.initial["untouched"])
            bridge.selectWeeklyStart("幻梦游园", 0)
            self.wait_for(lambda: not bridge.taskBusy)
            self.assertEqual(bridge.task_card.weekly_items[0]["start_label"], "不启用")
            bridge.selectGame(1)
            self.wait_for(lambda: not bridge.taskBusy)
            self.assertEqual(bridge.task_card.daily_items, [])
            bridge.selectGame(0)
            self.wait_for(lambda: not bridge.taskBusy)
            self.assertIn("凝素领域", bridge.task_card.daily_items[0]["task_label"])
            self.assertEqual(pid, client._process.processId())
            with patch.object(bridge.launch, "launchAll") as launch:
                bridge.launchAll()
                bridge.maybe_auto_launch()
                launch.assert_not_called()
            # 明确杀死所属测试后端，窗口保留并允许用户刷新重连。
            client._process.kill()
            self.wait_for(lambda: "连接断开" in bridge.taskStatus)
            self.assertFalse(bridge.taskBusy)
            bridge.refreshTasks()
            self.wait_for(lambda: bridge.taskStatus == "已同步")
            self.assertIn("凝素领域", bridge.task_card.daily_items[0]["task_label"])
            bridge.close_cli()
            self.assertEqual(client._process.state(), QProcess.NotRunning)
            with FileLease(self.root / ".update/runtime.lock") as lease:
                self.assertIsNotNone(lease.stream)

    def test_stale_responses_do_not_replace_current_card(self):
        client = DeferredClient()
        games = SimpleNamespace(current_game={"script_name": "A", "display_name": "甲"})
        controller = CliTaskCardController(games, Mock(), Mock(), client)
        controller.refresh()
        games.current_game = {"script_name": "B", "display_name": "乙"}
        controller.refresh()
        view = {"script": {"script_name": "B"}, "dailies": [], "weeklies": []}
        client.requests[1][2](view, None)
        client.requests[0][2](
            {"script": {"script_name": "A"}, "dailies": [], "weeklies": []}, None
        )
        self.assertEqual(controller._view["script"]["script_name"], "B")
        self.assertFalse(controller.busy)

    def test_write_failure_refreshes_without_replaying(self):
        client = DeferredClient()
        games = SimpleNamespace(current_game={"script_name": "A", "display_name": "甲"})
        toast = Mock()
        controller = CliTaskCardController(games, Mock(), toast, client)
        controller._view = {"dailies": [], "weeklies": [{"weekly_name": "周常"}]}
        controller.selectWeeklyStart("周常", 0)
        self.assertTrue(controller.busy)
        client.requests[0][2](
            None,
            {
                "code": "operation_failed",
                "message": "部分写入失败",
                "refresh_required": True,
            },
        )
        self.assertEqual(
            [r[0] for r in client.requests], ["weekly.start", "script.view"]
        )
        toast.assert_called_once_with("部分写入失败")

    def test_fragmented_utf8_and_stderr_do_not_block_event_loop(self):
        code = """
import json, sys, time
request = json.loads(sys.stdin.readline())
sys.stderr.write('x' * 100000)
sys.stderr.flush()
payload = (json.dumps({'protocol_version': 1, 'id': request['id'], 'result': {'name': '中文'}}, ensure_ascii=False) + '\\n').encode('utf-8')
cut = payload.index('中'.encode('utf-8')) + 1
sys.stdout.buffer.write(payload[:cut]); sys.stdout.buffer.flush()
time.sleep(0.1)
sys.stdout.buffer.write(payload[cut:]); sys.stdout.buffer.flush()
sys.stdin.read()
"""
        client = self.client([sys.executable, "-u", "-c", code])
        received, ticks = [], []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(5)
        self.addCleanup(timer.stop)
        with patch("src.gui.cli_client.logger.info"):
            client.request(
                "app.snapshot",
                {},
                lambda result, error: received.append((result, error)),
            )
            self.wait_for(lambda: bool(received))
        self.assertEqual(received, [({"name": "中文"}, None)])
        self.assertGreater(len(ticks), 2)

    def test_process_failures_report_once_and_clear_pending(self):
        cases = (
            ("exit", [sys.executable, "-c", "raise SystemExit(3)"], 1000),
            ("timeout", [sys.executable, "-c", "import time; time.sleep(60)"], 100),
            (
                "bad_json",
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "import sys; sys.stdin.readline(); sys.stdout.write('bad\\n'); sys.stdout.flush(); sys.stdin.read()",
                ],
                1000,
            ),
        )
        for name, command, timeout in cases:
            with self.subTest(name=name):
                client = self.client(command, timeout)
                received = []
                client.request(
                    "daily.select",
                    {},
                    lambda result, error, received=received: received.append(
                        (result, error)
                    ),
                )
                self.wait_for(lambda received=received: bool(received))
                self.wait_for(
                    lambda client=client: client._process.state() == QProcess.NotRunning
                )
                self.assertEqual(len(received), 1)
                self.assertEqual(received[0][1]["code"], "transport_failed")
                self.assertTrue(received[0][1]["refresh_required"])
                self.assertEqual(client._pending, {})
                self.assertEqual(client._outgoing, [])

    def test_qml_menus_send_integer_and_boolean_values(self):
        result = subprocess.run(
            [sys.executable, "-m", "tests.support.cli_gui_scene"],
            cwd=PROJECT_ROOT,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=40,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("ReferenceError", result.stderr)
        self.assertNotIn("TypeError", result.stderr)
