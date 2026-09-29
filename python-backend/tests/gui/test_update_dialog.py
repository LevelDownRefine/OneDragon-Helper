"""真实 Qt 事件循环验证手动更新的线程与交互边界。"""

import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.gui.controllers.update import UpdateController
from src.update.package import UpdateCancelled, UpdateError
from src.update.service import (
    PreparedUpdate,
    ReleaseUpdate,
    UpdateInfo,
)
from tests.gui.helpers import get_app


class TestUpdateDialog(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self.service = Mock()
        self.service.get_update_info.return_value = UpdateInfo("1.0.0")
        self.release = ReleaseUpdate(
            "1.1.0", "修复与改进\n<不作为 HTML 渲染>", "zip", "sha", 2048
        )
        self.service.check_update.return_value = self.release
        self.service.prepare_update.return_value = PreparedUpdate(
            Path("unused"), "1.1.0"
        )
        self.service.start_update.return_value = Path("result.json")
        self.ctrl = UpdateController(self.service)

    def tearDown(self):
        self.ctrl.shutdown()
        self.app.processEvents()
        if self.ctrl._dialog is not None:
            self.ctrl._close()
        self.ctrl.deleteLater()
        self.app.processEvents()

    def wait_for(self, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition(), "更新 UI 未在规定时间内完成")

    def open_available(self):
        self.ctrl.open()
        self.wait_for(lambda: self.ctrl._worker is None)
        return self.ctrl._dialog

    def click_and_wait(self, dialog):
        QTest.mouseClick(dialog.action_button, Qt.LeftButton)
        self.wait_for(lambda: self.ctrl._worker is None)

    def test_explicit_check_shows_release_and_previous_result(self):
        self.service.get_update_info.assert_not_called()
        self.service.check_update.assert_not_called()
        self.service.get_update_info.return_value = UpdateInfo(
            "1.0.0",
            previous_result={"status": "failed", "error": "文件被占用，已恢复旧版"},
        )
        main_thread = threading.get_ident()
        threads = []

        def check():
            threads.append(threading.get_ident())
            return self.release

        self.service.check_update.side_effect = check
        dialog = self.open_available()
        self.assertEqual(len(threads), 1)
        self.assertNotEqual(threads[0], main_thread)
        self.assertIn("1.0.0", dialog.version_label.text())
        self.assertIn("1.1.0", dialog.status_label.text())
        self.assertEqual(dialog.notes.toPlainText(), self.release.notes)
        self.assertEqual(dialog.action_button.text(), "下载更新")
        self.assertIn("文件被占用", dialog.previous_label.text())
        self.assertTrue(dialog.previous_label.isVisible())
        self.service.prepare_update.assert_not_called()
        self.service.start_update.assert_not_called()

    def test_latest_version_can_be_checked_again(self):
        self.service.check_update.return_value = None
        dialog = self.open_available()
        self.assertIn("最新版本", dialog.status_label.text())
        self.click_and_wait(dialog)
        self.assertEqual(self.service.check_update.call_count, 2)
        self.service.prepare_update.assert_not_called()

    def test_unsupported_build_has_release_link_and_never_checks_network(self):
        self.service.get_update_info.return_value = UpdateInfo(
            "源码运行", "请下载正式版"
        )
        self.ctrl.open()
        dialog = self.ctrl._dialog
        self.assertFalse(dialog.action_button.isVisible())
        self.assertIn("正式版", dialog.status_label.text())
        with patch(
            "src.gui.controllers.update.QDesktopServices.openUrl", return_value=True
        ) as browse:
            QTest.mouseClick(dialog.releases_button, Qt.LeftButton)
        self.assertEqual(browse.call_args.args[0].host(), "github.com")
        self.service.check_update.assert_not_called()

    def test_check_error_can_retry(self):
        self.service.check_update.side_effect = [OSError("网络不可用"), self.release]
        with self.assertLogs("src.gui.controllers.update", level="ERROR"):
            dialog = self.open_available()
        self.assertIn("网络不可用", dialog.status_label.text())
        self.click_and_wait(dialog)
        self.assertEqual(dialog.action_button.text(), "下载更新")

    def test_download_stays_responsive_and_cancels_on_close_or_shutdown(self):
        entered = threading.Event()
        cancelled_seen = threading.Event()

        def download(_release, *, progress, cancelled):
            progress(1024, 2048)
            entered.set()
            if cancelled.wait(3):
                cancelled_seen.set()
            raise UpdateCancelled("cancelled")

        for action in ("close", "shutdown"):
            with self.subTest(action=action):
                entered.clear()
                cancelled_seen.clear()
                with patch.object(
                    self.service, "prepare_update", side_effect=download
                ) as prepare:
                    dialog = self.open_available()
                    QTest.mouseClick(dialog.action_button, Qt.LeftButton)
                    self.wait_for(entered.is_set)
                    self.wait_for(lambda current=dialog: current.progress.value() == 50)
                    QTest.mouseClick(dialog.action_button, Qt.LeftButton)
                    responsive = threading.Event()
                    QTimer.singleShot(0, responsive.set)
                    self.wait_for(responsive.is_set)
                    if action == "close":
                        QTest.mouseClick(dialog.close_button, Qt.LeftButton)
                    else:
                        self.ctrl.shutdown()
                        self.assertFalse(self.ctrl._worker.isRunning())
                    self.wait_for(lambda: self.ctrl._dialog is None)
                    self.assertTrue(cancelled_seen.is_set(), "取消没有到达工作线程")
                    prepare.assert_called_once()
                    self.service.start_update.assert_not_called()

    def test_escape_during_check_waits_for_worker_before_closing(self):
        release = threading.Event()

        def check():
            release.wait(3)
            return self.release

        self.service.check_update.side_effect = check
        self.ctrl.open()
        dialog = self.ctrl._dialog
        QTest.keyClick(dialog, Qt.Key_Escape)
        self.assertIn("取消", dialog.status_label.text())
        self.assertIsNotNone(self.ctrl._worker)
        release.set()
        self.wait_for(lambda: self.ctrl._dialog is None)
        self.service.prepare_update.assert_not_called()

    def test_close_before_or_after_download_neither_installs_nor_quits(self):
        for phase in ("available", "downloaded"):
            with (
                self.subTest(phase=phase),
                patch.object(QApplication, "quit") as quit_app,
            ):
                self.service.prepare_update.reset_mock()
                dialog = self.open_available()
                if phase == "downloaded":
                    self.click_and_wait(dialog)
                    self.assertEqual(dialog.action_button.text(), "安装并重启")
                    self.assertIn("校验完成", dialog.status_label.text())
                    QTest.keyClick(dialog, Qt.Key_Escape)
                else:
                    self.service.prepare_update.assert_not_called()
                    dialog.close()
                self.assertIsNone(self.ctrl._dialog)
                self.service.start_update.assert_not_called()
                quit_app.assert_not_called()

    def test_install_error_keeps_window_and_retry_exits_only_after_ready(self):
        ready = threading.Event()
        self.service.start_update.side_effect = UpdateError("仍有任务运行")
        dialog = self.open_available()
        self.click_and_wait(dialog)
        with patch.object(QApplication, "quit") as quit_app:
            with self.assertLogs("src.gui.controllers.update", level="ERROR"):
                self.click_and_wait(dialog)
            quit_app.assert_not_called()
            self.assertTrue(dialog.isVisible())
            self.assertIn("任务运行", dialog.status_label.text())
            self.service.start_update.side_effect = lambda _prepared: ready.wait(3)
            QTest.mouseClick(dialog.action_button, Qt.LeftButton)
            QTest.keyClick(dialog, Qt.Key_Escape)
            self.assertIs(self.ctrl._dialog, dialog)
            self.assertFalse(dialog.close_button.isEnabled())
            quit_app.assert_not_called()
            ready.set()
            self.wait_for(lambda: self.ctrl._worker is None)
            quit_app.assert_called_once_with()
        self.assertIsNone(self.ctrl._dialog)
        self.assertEqual(self.service.start_update.call_count, 2)
