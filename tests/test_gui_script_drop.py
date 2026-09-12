"""外部脚本拖入窗口：URL / 快捷方式解析、添加与拖放动作。"""

import ctypes
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from ctypes import wintypes
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.gui.controllers.game_list import GameListController
from src.gui.file_drop import WindowsFileDrop
from src.gui.main_window import QmlBridge
from src.service.app_service import AppService
from src.utils.utils_config import build_script_entry
from src.utils.utils_sub_config import get_script_name
from src.utils.utils_yaml import load_yaml

_app = QApplication.instance() or QApplication([])


class TestDroppedScripts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = MagicMock()
        self.service.build_script_entry.side_effect = build_script_entry
        self.reload = MagicMock()
        self.toast = MagicMock()
        self.ctrl = GameListController(self.service, self.toast, self.reload)
        self.added = MagicMock()
        self.ctrl.gameAdded.connect(self.added)
        self.service.add_script.side_effect = lambda entry: self.ctrl._games.append(
            {"script_name": get_script_name(entry), "script_data": entry}
        )

    def file_url(self, name):
        path = Path(self.temp.name) / name
        path.write_text("", encoding="utf-8")
        return QUrl.fromLocalFile(str(path))

    def test_adds_multiple_unicode_and_encoded_paths(self):
        urls = [
            self.file_url(name) for name in ("鸣潮 100% #1.EXE", "task.py", "run.bat")
        ]
        self.assertTrue(self.ctrl.canDropScripts(urls))
        self.service.add_script.assert_not_called()
        with patch("src.gui.dialogs.pick_file") as picker:
            self.assertTrue(self.ctrl.dropScripts(urls))
        picker.assert_not_called()
        entries = [call.args[0] for call in self.service.add_script.call_args_list]
        self.assertEqual(
            [entry["script_path"] for entry in entries],
            [os.path.normpath(url.toLocalFile()) for url in urls],
        )
        self.assertEqual(
            [entry["script_type"] for entry in entries],
            ["external", "python", "external"],
        )
        self.assertEqual(self.added.call_count, 3)
        self.toast.assert_called_once_with("已添加 3 个脚本")
        for url in urls:
            self.assertTrue(Path(url.toLocalFile()).is_file())

    def test_rejects_empty_remote_missing_directory_and_unsupported_files(self):
        invalid_batches = [
            [],
            [QUrl("https://example.com/run.exe")],
            [QUrl.fromLocalFile(str(Path(self.temp.name) / "missing.py"))],
            [QUrl.fromLocalFile(self.temp.name)],
            [self.file_url("notes.txt")],
            [self.file_url("good.py"), self.file_url("image.png")],
        ]
        for urls in invalid_batches:
            with self.subTest(urls=urls):
                self.assertFalse(self.ctrl.canDropScripts(urls))
                self.assertFalse(self.ctrl.dropScripts(urls))
        self.service.add_script.assert_not_called()
        self.reload.assert_not_called()

    def test_rechecks_file_after_drag_enter(self):
        url = self.file_url("gone.py")
        self.assertTrue(self.ctrl.canDropScripts([url]))
        Path(url.toLocalFile()).unlink()
        self.assertFalse(self.ctrl.dropScripts([url]))
        self.service.add_script.assert_not_called()

    def test_duplicate_exe_is_not_added_or_renamed(self):
        url = self.file_url("same.exe")
        self.assertTrue(self.ctrl.dropScripts([url]))
        self.assertFalse(self.ctrl.dropScripts([url]))
        self.service.add_script.assert_called_once()
        self.toast.assert_called_with("脚本已存在：same")

    def test_same_named_python_scripts_keep_existing_suffix_behavior(self):
        url = self.file_url("same.py")
        self.assertTrue(self.ctrl.dropScripts([url, url]))
        self.assertEqual(
            [g["script_name"] for g in self.ctrl.games], ["same", "same_1"]
        )

    def test_save_failure_refreshes_and_reports_without_success(self):
        self.service.add_script.side_effect = OSError("disk unavailable")
        with self.assertLogs("src.gui.controllers.game_list", level="WARNING"):
            self.assertFalse(self.ctrl.dropScripts([self.file_url("task.py")]))
        self.reload.assert_called_once()
        self.added.assert_not_called()
        self.toast.assert_called_with("添加脚本未完成：disk unavailable")

    def test_shortcuts_add_the_target_script(self):
        for suffix in ("exe", "bat", "py"):
            with self.subTest(suffix=suffix):
                target = self.file_url(f"目标 {suffix}.{suffix}").toLocalFile()
                shortcut = self.file_url(f"桌面快捷方式-{suffix}.LNK")
                arguments = '--profile "中文 100% #1" --daily'
                with patch(
                    "src.utils.utils_config.read_shortcut",
                    return_value=(target, arguments, str(Path(target).parent)),
                ):
                    self.assertTrue(self.ctrl.canDropScripts([shortcut]))
                    self.assertTrue(self.ctrl.dropScripts([shortcut]))
                entry = self.service.add_script.call_args.args[0]
                self.assertEqual(entry["script_path"], os.path.normpath(target))
                self.assertEqual(
                    entry["script_type"], "python" if suffix == "py" else "external"
                )
                self.assertEqual(entry["script_arguments"], arguments)

    def test_broken_and_unsupported_shortcut_targets_are_rejected(self):
        shortcut = self.file_url("bad.lnk")
        for target in (
            "",
            str(Path(self.temp.name) / "gone.exe"),
            self.temp.name,
            self.file_url("notes.txt").toLocalFile(),
        ):
            with (
                self.subTest(target=target),
                patch(
                    "src.utils.utils_config.read_shortcut",
                    return_value=(target, "", ""),
                ),
                self.assertLogs("src.gui.controllers.game_list", level="WARNING"),
            ):
                self.assertFalse(self.ctrl.dropScripts([shortcut]))
                self.assertIn("bad.lnk", self.toast.call_args.args[0])
        self.service.add_script.assert_not_called()

    def test_batch_failure_is_reported_once_regardless_of_order(self):
        urls = [
            self.file_url(name) for name in ("first.exe", "second.exe", "third.exe")
        ]
        for failed_index in range(3):
            with self.subTest(failed_index=failed_index):
                self.ctrl._games.clear()
                self.toast.reset_mock()
                self.added.reset_mock()
                self.service.add_script.side_effect = [
                    PermissionError("disk unavailable") if i == failed_index else None
                    for i in range(3)
                ]
                with self.assertLogs("src.gui.controllers.game_list", level="WARNING"):
                    self.assertTrue(self.ctrl.dropScripts(urls))
                self.toast.assert_called_once()
                message = self.toast.call_args.args[0]
                self.assertIn("已添加 2 个脚本，失败 1 个", message)
                self.assertIn(Path(urls[failed_index].toLocalFile()).name, message)
                self.assertIn("disk unavailable", message)
                self.assertEqual(self.added.call_count, 2)

    def test_batch_reports_duplicates_and_successes_together(self):
        duplicate = self.file_url("existing.exe")
        self.assertTrue(self.ctrl.dropScripts([duplicate]))
        self.toast.reset_mock()
        self.assertTrue(self.ctrl.dropScripts([duplicate, self.file_url("new.exe")]))
        self.toast.assert_called_once()
        message = self.toast.call_args.args[0]
        self.assertIn("已添加 1 个脚本，重复 1 个", message)
        self.assertIn("existing.exe", message)

    def test_unreadable_shortcut_does_not_hide_another_success(self):
        with (
            patch(
                "src.utils.utils_config.read_shortcut", side_effect=OSError("bad link")
            ),
            self.assertLogs("src.gui.controllers.game_list", level="WARNING"),
        ):
            self.assertTrue(
                self.ctrl.dropScripts(
                    [self.file_url("bad.lnk"), self.file_url("ok.exe")]
                )
            )
        self.service.add_script.assert_called_once()
        self.toast.assert_called_once()
        self.assertIn("已添加 1 个脚本，失败 1 个", self.toast.call_args.args[0])
        self.assertIn("bad.lnk", self.toast.call_args.args[0])
        self.assertIn("bad link", self.toast.call_args.args[0])

    def test_batch_all_failures_keep_each_filename_and_reason(self):
        self.service.add_script.side_effect = OSError("disk unavailable")
        with self.assertLogs("src.gui.controllers.game_list", level="WARNING"):
            self.assertFalse(
                self.ctrl.dropScripts(
                    [self.file_url("one.exe"), self.file_url("two.exe")]
                )
            )
        self.toast.assert_called_once()
        message = self.toast.call_args.args[0]
        self.assertIn("已添加 0 个脚本，失败 2 个", message)
        self.assertIn("one.exe", message)
        self.assertIn("two.exe", message)
        self.assertIn("disk unavailable", message)
        self.added.assert_not_called()


class TestNativeDropPersistence(unittest.TestCase):
    def test_non_client_exe_drop_saves_config_and_updates_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.yml"
            weekly = root / "weekly.yml"
            exe = root / "拖入的脚本 100%.exe"
            exe.write_bytes(b"")
            config.write_text("script_list: []\n", encoding="utf-8")
            shell = MagicMock()
            shell.DragQueryPoint.return_value = False

            def query_file(handle, index, buffer, length):
                if index == 0xFFFFFFFF:
                    return 1
                if buffer is not None:
                    buffer.value = str(exe)
                return len(str(exe))

            shell.DragQueryFileW.side_effect = query_file
            window = MagicMock()
            window.winId.return_value = 1234
            with (
                patch(
                    "src.utils.utils_config.require_config_yml_path",
                    return_value=str(config),
                ),
                patch(
                    "src.utils.utils_config.get_config_yml_path_under_root",
                    return_value=str(config),
                ),
                patch(
                    "src.utils.utils_weekly.get_weekly_yml_path_under_root",
                    return_value=str(weekly),
                ),
                patch.object(AppService, "get_dungeon_map", return_value={}),
                patch.object(AppService, "get_weekly_map", return_value=[]),
                patch(
                    "src.gui.controllers.background.BackgroundController.resolve_bg",
                    return_value=None,
                ),
                patch("src.gui.controllers.task_card.get_dungeon", return_value=None),
                patch("src.gui.controllers.task_card.get_sequence", return_value=None),
                patch(
                    "src.gui.file_drop.ctypes.WinDLL",
                    side_effect=[shell, MagicMock(), MagicMock()],
                    create=True,
                ),
                patch(
                    "src.gui.file_drop.QGuiApplication.modalWindow", return_value=None
                ),
            ):
                bridge = QmlBridge()
                toasts = []
                bridge.toastRequested.connect(toasts.append)
                handler = WindowsFileDrop(window, bridge.dropScripts)
                message = wintypes.MSG(hWnd=1234, message=0x233, wParam=5678)
                handler.nativeEventFilter(
                    b"windows_generic_MSG", ctypes.addressof(message)
                )
                shell.DragFinish.assert_called_once_with(5678)
                # 此处不 mock 定时器、添加接口或写盘，验证异步回调真正走完全链路。
                QTest.qWait(150)
                entry = load_yaml(str(config))["script_list"][0]
                self.assertEqual(entry["script_path"], str(exe))
                self.assertEqual(entry["script_type"], "external")
                self.assertEqual(bridge.gameModel.rowCount(), 1)
                self.assertEqual(
                    bridge.games[0]["script_data"]["script_path"], str(exe)
                )
                self.assertIn(
                    bridge.games[0]["script_name"],
                    load_yaml(str(weekly))["weekly_timeouts"],
                )
                self.assertIn(f"已添加 {entry['display_name']}", toasts)


class TestQmlScriptDrop(unittest.TestCase):
    def test_drop_area_and_copy_action(self):
        code = textwrap.dedent(
            """
            import tempfile
            from pathlib import Path
            from unittest.mock import patch
            from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
            from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
            from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
            from PySide6.QtQuick import QQuickItem
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            from src.gui.controllers.background import BackgroundController
            from src.gui.main_window import QmlBridge
            from src.service.app_service import AppService
            from tests.test_qml_launcher import _make_bridge

            app = QApplication.instance()
            with (
                tempfile.TemporaryDirectory() as directory,
                patch.object(AppService, "get_dungeon_map", return_value={}),
                patch.object(AppService, "get_weekly_map", return_value=[]),
                patch.object(BackgroundController, "resolve_bg", return_value=None),
                patch("src.gui.controllers.task_card.get_dungeon", return_value=None),
                patch("src.gui.controllers.task_card.get_sequence", return_value=None),
            ):
                bridge = _make_bridge()
                qmlRegisterSingletonInstance(QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)
                engine = QQmlApplicationEngine()
                engine.addImageProvider("scripticon", bridge.game_list.icon_provider)
                engine.addImageProvider("uiicon", bridge.ui_icon_provider)
                engine.load(QUrl.fromLocalFile(str(Path("src/gui/qml/main.qml").resolve())))
                assert len(engine.rootObjects()) == 1
                window = engine.rootObjects()[0]
                highlight = window.findChild(QQuickItem, "scriptDropHighlight")
                window.requestActivate()
                QTest.qWait(200)
                paths = [Path(directory) / name for name in ("脚本 100%.py", "another.bat")]
                for path in paths:
                    path.write_text("", encoding="utf-8")
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
                actions = Qt.CopyAction | Qt.MoveAction

                def enter(point, data=mime, supported=actions):
                    event = QDragEnterEvent(point, supported, data, Qt.LeftButton, Qt.NoModifier)
                    app.sendEvent(window, event)
                    QTest.qWait(50)
                    return event

                with patch.object(bridge.game_list, "dropScripts", return_value=True) as add:
                    assert enter(QPoint(600, 300)).isAccepted()
                    assert highlight.isVisible()
                    add.assert_not_called()
                    drop = QDropEvent(QPointF(600, 300), actions, mime, Qt.LeftButton, Qt.NoModifier)
                    drop.setDropAction(Qt.MoveAction)
                    app.sendEvent(window, drop)
                    QTest.qWait(100)
                    assert drop.isAccepted() and drop.dropAction() == Qt.CopyAction
                    add.assert_called_once_with(mime.urls())
                    assert not highlight.isVisible()

                # 左栏、右侧按钮、启动按钮上方都能接收，离开时恢复。
                for point in (QPoint(40, 180), QPoint(1238, 166), QPoint(1000, 665)):
                    assert enter(point).isAccepted()
                    app.sendEvent(window, QDragLeaveEvent())
                    assert not highlight.isVisible()
                assert not enter(QPoint(40, 180), supported=Qt.MoveAction).isAccepted()
                bad = QMimeData()
                bad.setUrls([QUrl("https://example.com/game.exe")])
                assert not enter(QPoint(40, 180), data=bad).isAccepted()

                # 新拖放层不应拦截原有脚本点击与内部拖拽重排。
                QTest.mouseClick(window, Qt.LeftButton, pos=QPoint(40, 110))
                assert bridge.currentIndex == 1
                with patch.object(bridge.game_list, "reorderGames") as reorder:
                    QTest.mousePress(window, Qt.LeftButton, pos=QPoint(40, 48))
                    QTest.mouseMove(window, QPoint(40, 118), delay=50)
                    QTest.mouseRelease(window, Qt.LeftButton, pos=QPoint(40, 118))
                    reorder.assert_called_once_with(0, 1)
                window.close()
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("TypeError", result.stderr)
        self.assertNotIn("ReferenceError", result.stderr)
