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
from src.service.update_package import UpdateError
from src.service.update_service import (
    PreparedUpdate,
    ReleaseUpdate,
    UpdateCancelled,
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

    def test_constructing_controller_does_not_read_or_check_updates(self):
        self.service.get_update_info.assert_not_called()
        self.service.check_update.assert_not_called()

    def test_check_runs_off_gui_thread_and_does_not_download(self):
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

    def test_download_progress_cancel_and_no_duplicate_requests(self):
        entered = threading.Event()

        def download(_release, *, progress, cancelled):
            progress(1024, 2048)
            entered.set()
            self.assertTrue(cancelled.wait(3), "取消没有到达工作线程")
            raise UpdateCancelled("cancelled")

        self.service.prepare_update.side_effect = download
        dialog = self.open_available()
        QTest.mouseClick(dialog.action_button, Qt.LeftButton)
        self.wait_for(entered.is_set)
        self.wait_for(lambda: dialog.progress.value() == 50)
        QTest.mouseClick(dialog.action_button, Qt.LeftButton)
        responsive = []
        QTimer.singleShot(0, lambda: responsive.append(True))
        self.wait_for(lambda: bool(responsive))
        QTest.mouseClick(dialog.close_button, Qt.LeftButton)
        self.wait_for(lambda: self.ctrl._dialog is None)
        self.service.prepare_update.assert_called_once()
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

    def test_close_after_download_never_installs(self):
        dialog = self.open_available()
        self.click_and_wait(dialog)
        self.assertEqual(dialog.action_button.text(), "安装并重启")
        self.assertIn("校验完成", dialog.status_label.text())
        QTest.keyClick(dialog, Qt.Key_Escape)
        self.assertIsNone(self.ctrl._dialog)
        self.service.start_update.assert_not_called()

    def test_window_close_before_download_keeps_application_running(self):
        dialog = self.open_available()
        with patch.object(QApplication, "quit") as quit_app:
            dialog.close()
        self.assertIsNone(self.ctrl._dialog)
        quit_app.assert_not_called()
        self.service.prepare_update.assert_not_called()

    def test_install_error_keeps_window_and_retry_exits_only_after_ready(self):
        self.service.start_update.side_effect = [
            UpdateError("仍有任务运行"),
            Path("result.json"),
        ]
        dialog = self.open_available()
        self.click_and_wait(dialog)
        with patch.object(QApplication, "quit") as quit_app:
            with self.assertLogs("src.gui.controllers.update", level="ERROR"):
                self.click_and_wait(dialog)
            quit_app.assert_not_called()
            self.assertTrue(dialog.isVisible())
            self.assertIn("任务运行", dialog.status_label.text())
            self.click_and_wait(dialog)
            quit_app.assert_called_once_with()
        self.assertIsNone(self.ctrl._dialog)
        self.assertEqual(self.service.start_update.call_count, 2)

    def test_window_cannot_be_closed_during_installer_handoff(self):
        ready = threading.Event()
        self.service.start_update.side_effect = lambda _prepared: ready.wait(3)
        dialog = self.open_available()
        self.click_and_wait(dialog)
        with patch.object(QApplication, "quit") as quit_app:
            QTest.mouseClick(dialog.action_button, Qt.LeftButton)
            QTest.keyClick(dialog, Qt.Key_Escape)
            self.assertIs(self.ctrl._dialog, dialog)
            self.assertFalse(dialog.close_button.isEnabled())
            quit_app.assert_not_called()
            ready.set()
            self.wait_for(lambda: self.ctrl._worker is None)
            quit_app.assert_called_once_with()

    def test_previous_install_failure_is_visible(self):
        self.service.get_update_info.return_value = UpdateInfo(
            "1.0.0",
            previous_result={"status": "failed", "error": "文件被占用，已恢复旧版"},
        )
        dialog = self.open_available()
        self.assertIn("文件被占用", dialog.previous_label.text())
        self.assertTrue(dialog.previous_label.isVisible())

    def test_shutdown_waits_for_download_worker(self):
        entered = threading.Event()
        stopped = threading.Event()

        def download(_release, *, progress, cancelled):
            entered.set()
            cancelled.wait(3)
            stopped.set()
            raise UpdateCancelled("quit")

        self.service.prepare_update.side_effect = download
        dialog = self.open_available()
        QTest.mouseClick(dialog.action_button, Qt.LeftButton)
        self.wait_for(entered.is_set)
        self.ctrl.shutdown()
        self.assertTrue(stopped.is_set())
        self.assertFalse(self.ctrl._worker.isRunning())
        self.wait_for(lambda: self.ctrl._dialog is None)
