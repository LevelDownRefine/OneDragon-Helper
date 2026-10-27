"""真实子进程验证 stdin 交付超时与成功后的独立运行。"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from gui.controllers.cli_launch import CliLaunchController
from tests.gui.helpers import get_app


class RunStarterTests(TestCase):
    def setUp(self):
        self.app = get_app()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.children = []
        self.ready_before_delivery = None
        self.addCleanup(self._cleanup_children)
        original = subprocess.Popen

        def spawn(*args, **kwargs):
            child = original(*args, **kwargs)
            self.children.append(child)
            if self.ready_before_delivery is not None:
                # 等子进程准备就绪后开始交付，排除解释器与控制台启动计时。
                deadline = time.monotonic() + 5
                while not self.ready_before_delivery.is_file():
                    if child.poll() is not None:
                        raise OSError("假进程在准备就绪前退出")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("假进程未报告准备就绪")
                    time.sleep(0.01)
            return child

        self.enterContext(
            patch("gui.controllers.cli_launch.subprocess.Popen", side_effect=spawn)
        )
        self.toast = Mock()
        self.controller = CliLaunchController(SimpleNamespace(), Mock(), self.toast)
        self.controller._starter._timeout_seconds = 0.5
        self.controller.active = True

    def _cleanup_children(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)

    def _wait(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while not condition():
            self.assertLess(time.monotonic(), deadline, "子进程或 Qt 回执未及时完成")
            self.app.processEvents()
            time.sleep(0.01)

    def _target(self, code):
        # 夹具仅用标准库；Windows venv redirector 另持 stdin 读端，
        # 也会让 kill 仅结束 launcher，故直接运行基础解释器。
        return {
            "program": getattr(sys, "_base_executable", sys.executable),
            "args": ["-c", code],
            "cwd": str(self.root),
            "env": {},
            "input": "x" * (128 * 1024),
        }

    def test_unread_stdin_times_out_reaps_child_and_releases_launch_state(self):
        self.controller._starter.start(self._target("import time; time.sleep(30)"))
        self._wait(lambda: not self.controller.active)
        self._wait(lambda: self.children[0].poll() is not None)
        self.assertEqual(len(self.children), 1)
        self.toast.assert_called_once()
        self.assertIn("交付超时", self.toast.call_args.args[0])
        self.assertIn("结果不确定", self.toast.call_args.args[0])

    def test_success_closes_stdin_and_keeps_child_alive_after_deadline(self):
        self.ready_before_delivery = self.root / "stdin-ready"
        self.controller._starter._timeout_seconds = 2
        self.controller._starter.start(
            self._target(
                "import sys,time; from pathlib import Path; "
                "Path('stdin-ready').touch(); "
                "Path('received').write_text(str(len(sys.stdin.read()))); "
                "time.sleep(30)"
            )
        )
        self._wait(lambda: not self.controller.active)
        self._wait(lambda: (self.root / "received").is_file())
        self.assertEqual((self.root / "received").read_text(), str(128 * 1024))
        deadline = time.monotonic() + 2.2
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertIsNone(self.children[0].poll())
        self.toast.assert_called_once()
        self.assertIn("已在独立控制台启动", self.toast.call_args.args[0])

    def test_closed_stdin_reports_failure_and_terminates_child(self):
        self.ready_before_delivery = self.root / "stdin-closed"
        self.controller._starter.start(
            self._target(
                "import os,time; from pathlib import Path; os.close(0); "
                "Path('stdin-closed').touch(); time.sleep(30)"
            )
        )
        self._wait(lambda: not self.controller.active)
        self._wait(lambda: self.children[0].poll() is not None)
        self.assertTrue(self.ready_before_delivery.is_file())
        self.toast.assert_called_once()
        self.assertIn("传递运行配置失败", self.toast.call_args.args[0])
