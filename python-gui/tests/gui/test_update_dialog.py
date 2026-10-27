"""真实更新窗口经 CLI 后台任务检查、下载、取消和交接安装。"""

import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from gui.controllers.cli_update import CliUpdateController
from tests.gui.helpers import get_app
from tests.gui.rpc_test_support import RpcHarness


class TestUpdateDialog(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self.rpc = RpcHarness()
        self.release = {
            "version": "1.1.0",
            "notes": "修复与改进\n<不作为 HTML 渲染>",
            "size": 2048,
        }
        self.view = {
            "version": "1.0.0",
            "unavailable_reason": "",
            "previous_result": None,
            "releases_url": "https://github.com/LevelDownRefine/OneDragon-Helper/releases/latest",
            "release": None,
            "prepared_version": None,
            "handoff_ready": False,
        }
        self.ctrl = CliUpdateController(self.rpc.session)

    def tearDown(self):
        self.ctrl._job._timer.stop()
        if self.ctrl._job.active:
            self.ctrl._job._finish()
        if self.ctrl._dialog is not None:
            self.ctrl._dialog.done(QDialog.Rejected)
        self.rpc.session.detach()
        self.ctrl.deleteLater()
        self.app.processEvents()

    def started(self):
        self.rpc.reply({"id": f"job-{len(self.rpc.requests)}"})
        self.ctrl._job._timer.stop()

    def poll(self, *, state="succeeded", result=None, error="", progress=None):
        job = self.ctrl._job
        job._timer.stop()
        job._poll()
        value = {"id": job.job_id, "kind": job.kind, "state": state}
        if state == "succeeded":
            value["result"] = result
        elif state == "failed":
            value["error"] = error
        if progress is not None:
            value["progress"] = progress
        self.rpc.reply(value)
        job._timer.stop()

    def begin_check(self):
        self.ctrl.open()
        self.assertEqual(self.rpc.requests[-1], ("update.view", {}))
        self.rpc.reply(self.view)
        self.assertEqual(self.rpc.requests[-1], ("update.check", {}))
        self.started()
        return self.ctrl._dialog

    def open_available(self):
        dialog = self.begin_check()
        self.poll(result={"release": self.release})
        return dialog

    def begin_download(self, dialog):
        QTest.mouseClick(dialog.action_button, Qt.LeftButton)
        self.assertEqual(self.rpc.requests[-1], ("update.download", {}))
        self.started()

    def download_ready(self, dialog):
        self.begin_download(dialog)
        self.poll(result={"version": "1.1.0"})

    def test_explicit_check_shows_release_and_previous_result(self):
        self.assertEqual(self.rpc.requests, [])
        self.view["previous_result"] = {
            "status": "failed",
            "error": "文件被占用，已恢复旧版",
        }
        dialog = self.open_available()
        self.assertIn("1.0.0", dialog.version_label.text())
        self.assertIn("1.1.0", dialog.status_label.text())
        self.assertEqual(dialog.notes.toPlainText(), self.release["notes"])
        self.assertEqual(dialog.action_button.text(), "下载更新")
        self.assertIn("文件被占用", dialog.previous_label.text())
        self.assertTrue(dialog.previous_label.isVisible())
        self.assertFalse(
            any(
                method in {"update.download", "update.install"}
                for method, _ in self.rpc.requests
            )
        )

    def test_latest_version_can_be_checked_again(self):
        dialog = self.begin_check()
        self.poll(result={"release": None})
        self.assertIn("最新版本", dialog.status_label.text())
        QTest.mouseClick(dialog.action_button, Qt.LeftButton)
        self.rpc.reply(self.view)
        self.started()
        self.poll(result={"release": None})
        self.assertEqual(
            [method for method, _ in self.rpc.requests].count("update.check"), 2
        )

    def test_unsupported_build_has_release_link_and_never_starts_check(self):
        self.view["unavailable_reason"] = "请下载正式版"
        self.ctrl.open()
        self.rpc.reply(self.view)
        dialog = self.ctrl._dialog
        self.assertFalse(dialog.action_button.isVisible())
        self.assertIn("正式版", dialog.status_label.text())
        with patch(
            "gui.controllers.cli_update.QDesktopServices.openUrl", return_value=True
        ) as browse:
            QTest.mouseClick(dialog.releases_button, Qt.LeftButton)
        self.assertEqual(browse.call_args.args[0].host(), "github.com")
        self.assertEqual(self.rpc.requests, [("update.view", {})])

    def test_check_error_can_retry(self):
        dialog = self.begin_check()
        self.poll(state="failed", error="网络不可用")
        self.assertIn("网络不可用", dialog.status_label.text())
        QTest.mouseClick(dialog.action_button, Qt.LeftButton)
        self.rpc.reply(self.view)
        self.started()
        self.poll(result={"release": self.release})
        self.assertEqual(dialog.action_button.text(), "下载更新")

    def test_download_stays_responsive_and_close_waits_for_cancelled_job(self):
        for close_action in ("button", "escape"):
            with self.subTest(close_action=close_action):
                dialog = self.open_available()
                self.begin_download(dialog)
                self.poll(state="running", progress={"received": 1024, "total": 2048})
                self.assertEqual(dialog.progress.value(), 50)
                responsive = []
                QTimer.singleShot(0, lambda result=responsive: result.append(True))
                QTest.qWait(10)
                self.assertEqual(responsive, [True])
                if close_action == "button":
                    QTest.mouseClick(dialog.close_button, Qt.LeftButton)
                else:
                    QTest.keyClick(dialog, Qt.Key_Escape)
                self.assertEqual(
                    self.rpc.requests[-1],
                    ("job.cancel", {"job_id": self.ctrl._job.job_id}),
                )
                self.assertIs(self.ctrl._dialog, dialog)
                self.assertIn("取消", dialog.status_label.text())
                self.rpc.reply(True)
                self.assertIs(self.ctrl._dialog, dialog)
                self.poll(state="cancelled")
                self.assertIsNone(self.ctrl._dialog)
        self.assertFalse(
            any(method == "update.install" for method, _ in self.rpc.requests)
        )

    def test_escape_during_check_waits_for_terminal_cancelled_state(self):
        dialog = self.begin_check()
        QTest.keyClick(dialog, Qt.Key_Escape)
        self.assertTrue(self.ctrl._job.active)
        self.assertIn("取消", dialog.status_label.text())
        self.rpc.reply(True)
        self.poll(state="cancelled")
        self.assertIsNone(self.ctrl._dialog)

    def test_close_before_or_after_download_neither_installs_nor_quits(self):
        for phase in ("available", "downloaded"):
            with (
                self.subTest(phase=phase),
                patch.object(QApplication, "quit") as quit_app,
            ):
                dialog = self.open_available()
                if phase == "downloaded":
                    self.download_ready(dialog)
                    self.assertEqual(dialog.action_button.text(), "安装并重启")
                    self.assertIn("校验完成", dialog.status_label.text())
                    QTest.keyClick(dialog, Qt.Key_Escape)
                else:
                    dialog.close()
                self.assertIsNone(self.ctrl._dialog)
                quit_app.assert_not_called()
        self.assertFalse(
            any(method == "update.install" for method, _ in self.rpc.requests)
        )

    def test_install_error_keeps_window_and_quits_only_after_ready(self):
        dialog = self.open_available()
        self.download_ready(dialog)
        with patch.object(QApplication, "quit") as quit_app:
            QTest.mouseClick(dialog.action_button, Qt.LeftButton)
            self.assertEqual(self.rpc.requests[-1], ("update.install", {}))
            self.started()
            self.poll(state="failed", error="仍有任务运行")
            quit_app.assert_not_called()
            self.assertTrue(dialog.isVisible())
            self.assertIn("任务运行", dialog.status_label.text())
            # 安装失败后重新检查会话，再显式下载/安装，不自动重放写操作。
            QTest.mouseClick(dialog.action_button, Qt.LeftButton)
            self.rpc.reply(self.view)
            self.started()
            self.poll(result={"release": self.release})
            self.download_ready(dialog)
            QTest.mouseClick(dialog.action_button, Qt.LeftButton)
            self.started()
            QTest.keyClick(dialog, Qt.Key_Escape)
            self.assertIs(self.ctrl._dialog, dialog)
            self.assertFalse(dialog.close_button.isEnabled())
            quit_app.assert_not_called()
            self.poll(result={"ready": True, "version": "1.1.0"})
            quit_app.assert_called_once_with()
        self.assertIsNone(self.ctrl._dialog)
        self.assertEqual(
            [method for method, _ in self.rpc.requests].count("update.install"), 2
        )
