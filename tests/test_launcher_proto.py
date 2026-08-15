"""测试 src/launcher_proto/launcher_proto.py：周常「周几起」选择与持久化。"""

import os
import unittest
from unittest.mock import MagicMock, patch

# 在导入 PySide6 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from src.launcher_proto import launcher_proto
from src.launcher_proto.launcher_proto import C_BLUE_TEXT, LauncherWindow

# 全局 QApplication 实例（测试共享）
_app = QApplication.instance() or QApplication([])

# 模块级持有 chip 引用，避免无 parent 的 QFrame 被垃圾回收
_chip_holder = []


def _make_window(script_name="ok-ww"):
    """构造测试用 LauncherWindow：跳过完整 __init__（避免文件 I/O 与 UI 构建），
    手动注入周常相关状态。"""
    win = LauncherWindow.__new__(LauncherWindow)
    win.games = [{"script_name": script_name, "display_name": "测试"}]
    win._current_index = 0
    win._dungeon_state = {}
    win._weekly_toggle_state = {}
    win.service = MagicMock()
    chip = QFrame()
    _chip_holder.append(chip)  # 保持引用，防止被垃圾回收
    win.weekly_chip_lbl = QLabel("", chip)
    win.weekly_ico_lbl = QLabel("", chip)
    win.weekly_name_lbl = QLabel("", chip)
    daily_chip = QFrame()
    _chip_holder.append(daily_chip)
    win.daily_chip_lbl = QLabel("", daily_chip)
    win.weekly_toggle = MagicMock()
    win.toast_lbl = MagicMock()
    return win


class TestRefreshWeeklyChip(unittest.TestCase):
    """_refresh_weekly_chip：按 supports_weekly 与已选起始日刷新 chip"""

    def test_unsupported_shows_disabled(self):
        """未支持周常的脚本 → chip 文字「未支持」不可点，toggle 禁用"""
        win = _make_window()
        with patch.object(launcher_proto, "_supports_weekly", return_value=False):
            win._refresh_weekly_chip()
        self.assertEqual(win.weekly_chip_lbl.text(), "未支持")
        self.assertEqual(win.weekly_chip_lbl.cursor().shape(), Qt.ArrowCursor)
        win.weekly_toggle.setEnabled.assert_called_once_with(False)

    def test_supported_enables_toggle(self):
        """支持周常的脚本 → toggle 可用"""
        win = _make_window()
        with patch.object(launcher_proto, "_supports_weekly", return_value=True):
            win._refresh_weekly_chip()
        win.weekly_toggle.setEnabled.assert_called_once_with(True)

    def test_supported_no_selection(self):
        """支持但未选起始日 → 「选择周几」可点（PointingHandCursor）"""
        win = _make_window()
        with patch.object(launcher_proto, "_supports_weekly", return_value=True):
            win._refresh_weekly_chip()
        self.assertEqual(win.weekly_chip_lbl.text(), "选择周几")
        self.assertEqual(win.weekly_chip_lbl.cursor().shape(), Qt.PointingHandCursor)

    def test_supported_with_selection(self):
        """支持且已选起始日 4 → 「周四起」"""
        win = _make_window()
        win._dungeon_state = {"ok-ww": {"weekly_start": 4}}
        with patch.object(launcher_proto, "_supports_weekly", return_value=True):
            win._refresh_weekly_chip()
        self.assertEqual(win.weekly_chip_lbl.text(), "周四起")
        self.assertIn("#0F1A2E", win.weekly_chip_lbl.parent().styleSheet())
        self.assertIn(C_BLUE_TEXT, win.weekly_ico_lbl.styleSheet())
        self.assertIn(C_BLUE_TEXT, win.weekly_name_lbl.styleSheet())

    def test_supported_missing_state_entry(self):
        """_dungeon_state 无该脚本条目 → 视为未选择"""
        win = _make_window()
        win._dungeon_state = {}
        with patch.object(launcher_proto, "_supports_weekly", return_value=True):
            win._refresh_weekly_chip()
        self.assertEqual(win.weekly_chip_lbl.text(), "选择周几")


class TestSetWeekly(unittest.TestCase):
    """_set_weekly：持久化 weekly_start、更新 chip、同步周常开关（UI 内存态）"""

    def test_persists_and_updates_chip(self):
        """选周四（4）→ _dungeon_state 落 weekly_start=4，chip「周四起」，save_ui_state 调用"""
        win = _make_window()
        win._set_weekly(4)
        self.assertEqual(win._dungeon_state["ok-ww"]["weekly_start"], 4)
        self.assertEqual(win.weekly_chip_lbl.text(), "周四起")
        win.service.save_ui_state.assert_called_once_with(win._dungeon_state)

    def test_keeps_existing_dungeon_fields(self):
        """已有 daily 字段时合并更新，不覆盖 dungeon/sequence"""
        win = _make_window()
        win._dungeon_state = {"ok-ww": {"dungeon": "无音区", "sequence": 2}}
        win._set_weekly(6)
        self.assertEqual(
            win._dungeon_state["ok-ww"],
            {"dungeon": "无音区", "sequence": 2, "weekly_start": 6},
        )

    def test_invalid_day_raises(self):
        """非法周几（0 / 8）应 assert"""
        win = _make_window()
        for bad in (0, 8):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                win._set_weekly(bad)

    def test_syncs_toggle_on_when_today_reached(self):
        """今天已是起始日（今天=周五 get_week_num=4，起始=周四4）→ 周常开关开启"""
        win = _make_window()
        with patch("src.utils_weekly.get_week_num", return_value=4):
            win._set_weekly(4)
        self.assertTrue(win._weekly_toggle_state["ok-ww"])
        win.weekly_toggle.set_on.assert_called_once_with(True)

    def test_syncs_toggle_off_when_today_before(self):
        """今天未到起始日（今天=周二 get_week_num=1，起始=周四4）→ 周常开关关闭"""
        win = _make_window()
        with patch("src.utils_weekly.get_week_num", return_value=1):
            win._set_weekly(4)
        self.assertFalse(win._weekly_toggle_state["ok-ww"])
        win.weekly_toggle.set_on.assert_called_once_with(False)


class TestWeeklyToggleState(unittest.TestCase):
    """周常开关内存态：纯 UI，不持久化、不写脚本配置"""

    def test_on_weekly_toggled_updates_memory_state(self):
        """点击开关（on=True）→ 只更新 _weekly_toggle_state，不写 gui_state.json"""
        win = _make_window()
        win._on_weekly_toggled(True)
        self.assertTrue(win._weekly_toggle_state["ok-ww"])
        win.service.save_ui_state.assert_not_called()

    def test_sync_weekly_toggle_applies_memory_state(self):
        """切游戏时把内存态同步到 UI toggle"""
        win = _make_window()
        win._weekly_toggle_state = {"ok-ww": True}
        win._sync_weekly_toggle()
        win.weekly_toggle.set_on.assert_called_once_with(True)

    def test_run_chain_passes_persisted_state(self):
        """运行链时把持久化 ui_state（含 weekly_start）传给 chain_gen，
        周常开关由 chain_gen 按周几起判断写入，toggle（enabled）不参与"""
        win = _make_window()
        win._dungeon_state = {"ok-ww": {"dungeon": "无音区", "weekly_start": 4}}
        win._weekly_toggle_state = {"ok-ww": True}
        win.service.generate_chain.return_value = "chain.yml"
        with (
            patch.object(launcher_proto, "build_script_command") as mock_build,
            patch.object(launcher_proto.subprocess, "Popen"),
            patch.object(win, "_toast"),
        ):
            mock_build.return_value = (["python", "--chain", "chain.yml"], ".", {})
            win._run_chain({"script_list": []}, {"ok-ww"}, "测试")
        _, kwargs = win.service.generate_chain.call_args
        self.assertEqual(
            kwargs["ui_state"],
            {"ok-ww": {"dungeon": "无音区", "weekly_start": 4}},
        )


class TestSetDailyKeepsWeekly(unittest.TestCase):
    """_set_daily 合并更新：不覆盖 weekly_start"""

    def test_daily_update_keeps_weekly_start(self):
        """先设周常再设日常 → weekly_start 保留"""
        win = _make_window()
        win._set_weekly(4)
        win._dungeon_state["ok-ww"].update({"dungeon": "无音区", "sequence": 2})
        win._set_daily("无音区", 2)
        self.assertEqual(win._dungeon_state["ok-ww"]["weekly_start"], 4)
        self.assertEqual(win._dungeon_state["ok-ww"]["dungeon"], "无音区")

    def test_clear_daily_keeps_weekly_start(self):
        """清空日常（None）→ 只删 dungeon/sequence，weekly_start 保留"""
        win = _make_window()
        win._dungeon_state = {
            "ok-ww": {"dungeon": "无音区", "sequence": 2, "weekly_start": 4}
        }
        win._set_daily(None, None)
        self.assertEqual(win._dungeon_state["ok-ww"], {"weekly_start": 4})


class TestReloadKeepsEnabledState(unittest.TestCase):
    """_reload_games（保存配置后）重建 rail 时保留脚本启用/停用状态"""

    def test_reload_preserves_enabled_state(self):
        """停用脚本 → 保存配置重建 → 停用状态保留，其余仍启用"""
        scripts = [
            {"display_name": "甲", "script_path": "scripts/a.py"},
            {"display_name": "乙", "script_path": "scripts/b.py"},
        ]
        with (
            patch.object(
                launcher_proto.ChainService,
                "load_config",
                return_value={"script_list": scripts},
            ),
            patch.object(launcher_proto.ChainService, "load_ui_state", return_value={}),
            patch.object(
                launcher_proto.LauncherWindow, "_load_wallpapers", return_value={}
            ),
        ):
            win = LauncherWindow()
            try:
                self.assertTrue(all(i.is_enabled() for i in win.game_icons))
                # 停用第一个脚本后保存配置（_reload_games 重建 rail）
                win.game_icons[0].set_enabled(False)
                win._reload_games()
                self.assertFalse(win.game_icons[0].is_enabled())
                self.assertTrue(win.game_icons[1].is_enabled())
            finally:
                win.close()


class TestShowWeeklyMenu(unittest.TestCase):
    """_show_weekly_menu：支持门控与菜单选项"""

    def test_unsupported_returns_without_menu(self):
        """未支持周常 → 直接返回，不 exec 菜单"""
        win = _make_window()
        with (
            patch.object(launcher_proto, "_supports_weekly", return_value=False),
            patch.object(launcher_proto.QMenu, "exec") as mock_exec,
        ):
            win._show_weekly_menu()
        mock_exec.assert_not_called()

    def test_supported_shows_seven_days(self):
        """支持周常 → 菜单含周一至周日 7 项（今天标注在对应项），选中项持久化"""
        win = _make_window()
        menu = MagicMock()
        slots = []
        menu.addAction.return_value.triggered.connect.side_effect = lambda slot: (
            slots.append(slot)
        )
        fake_menu_cls = MagicMock(return_value=menu)
        with (
            patch.object(launcher_proto, "_supports_weekly", return_value=True),
            patch.object(launcher_proto, "get_week_num", return_value=3),
            patch.object(launcher_proto, "QMenu", fake_menu_cls),
        ):
            win._show_weekly_menu()
        self.assertEqual(len(slots), 7)
        labels = [call.args[0] for call in menu.addAction.call_args_list]
        # 周四（today=3 → 4）标注「（今天）」，其余为纯星期名
        self.assertEqual(labels[3], "周四（今天）")
        labels[3] = "周四"
        self.assertEqual(
            labels,
            ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
        )
        # 触发「周四」项 → weekly_start=4
        slots[3]()
        self.assertEqual(win._dungeon_state["ok-ww"]["weekly_start"], 4)


if __name__ == "__main__":
    unittest.main()
