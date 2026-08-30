"""测试 src/config/subscript.py：脚本唯一标识、路径解析、脚本路径读取、默认条目构造"""

import unittest
from unittest import mock

from src.config.subscript import (
    check_script_name_uniqueness,
    default_script_entry,
    get_process_name,
    get_script_name,
    get_script_path,
    load_game_config,
    resolve_script_path,
)
from src.utils import get_root_dir, safe_path_join


class TestGetProcessName(unittest.TestCase):
    """测试 get_process_name：script_path basename 去后缀。"""

    def test_exe_basename(self):
        self.assertEqual(
            get_process_name("D:\\game_helper\\BetterGI\\BetterGI.exe"), "BetterGI"
        )

    def test_exe_with_spaces(self):
        self.assertEqual(
            get_process_name(
                "D:/game_helper/March7thAssistant_full/March7th Assistant.exe"
            ),
            "March7th-Assistant",
        )

    def test_edge_spaces_removed_not_replaced(self):
        """首尾空格（误输入）被去除而非替换成 -，句中空格才替换。"""
        self.assertEqual(get_process_name("D:/x/foo .exe"), "foo")
        self.assertEqual(get_process_name("D:/x/ foo .exe"), "foo")

    def test_python_script(self):
        self.assertEqual(get_process_name("scripts/mute.py"), "mute")

    def test_plain_name(self):
        self.assertEqual(get_process_name("ok-ww.exe"), "ok-ww")


class TestGetScriptKey(unittest.TestCase):
    """测试 get_script_name：exe 用进程名，脚本文件用 display_name。"""

    def test_exe_script_uses_process_name(self):
        script = {"display_name": "鸣潮", "script_path": "C:/game_helper/ok-ww.exe"}
        self.assertEqual(get_script_name(script), "ok-ww")

    def test_python_script_uses_display_name(self):
        script = {"display_name": "静音", "script_path": "scripts/mute.py"}
        self.assertEqual(get_script_name(script), "静音")

    def test_bat_script_uses_display_name(self):
        script = {"display_name": "启动脚本", "script_path": "scripts/start.bat"}
        self.assertEqual(get_script_name(script), "启动脚本")

    def test_exe_case_insensitive(self):
        script = {"display_name": "MAA", "script_path": "C:/game_helper/MAA.EXE"}
        self.assertEqual(get_script_name(script), "MAA")


class TestCheckScriptKeyUniqueness(unittest.TestCase):
    """测试 check_script_name_uniqueness：脚本唯一标识唯一性校验。"""

    def test_unique_ok(self):
        data = {
            "script_list": [
                {"display_name": "鸣潮", "script_path": "D:/a/ok-ww.exe"},
                {"display_name": "原神", "script_path": "D:/b/BetterGI.exe"},
                {"display_name": "静音", "script_path": "scripts/mute.py"},
            ]
        }
        check_script_name_uniqueness(data)  # 不应抛异常

    def test_duplicate_exe_raises(self):
        data = {
            "script_list": [
                {"display_name": "鸣潮1", "script_path": "D:/a/ok-ww.exe"},
                {"display_name": "鸣潮2", "script_path": "D:/b/ok-ww.exe"},
            ]
        }
        with self.assertRaises(AssertionError):
            check_script_name_uniqueness(data)

    def test_duplicate_display_name_raises(self):
        data = {
            "script_list": [
                {"display_name": "静音", "script_path": "scripts/a.py"},
                {"display_name": "静音", "script_path": "scripts/b.py"},
            ]
        }
        with self.assertRaises(AssertionError):
            check_script_name_uniqueness(data)


class TestResolveScriptPath(unittest.TestCase):
    """测试 resolve_script_path：相对→项目根绝对，绝对原样保留"""

    def test_relative_resolved_to_root(self):
        self.assertEqual(
            resolve_script_path("scripts/shutdown.bat"),
            safe_path_join(get_root_dir(), "scripts/shutdown.bat"),
        )

    def test_absolute_preserved(self):
        self.assertEqual(resolve_script_path("D:\\games\\x.exe"), "D:\\games\\x.exe")


class TestGetScriptPath(unittest.TestCase):
    """测试 get_script_path：相对 script_path 解析为基于项目根的绝对路径，绝对路径原样保留"""

    def test_relative_script_path_resolved_to_root(self):
        fake = {
            "script_list": [
                {"display_name": "自动关机", "script_path": "scripts/shutdown.bat"},
            ]
        }
        with (
            mock.patch("src.config.subscript._load_config_yml", return_value=fake),
            mock.patch("src.config.subscript.os.path.exists", return_value=True),
        ):
            got = get_script_path("自动关机")
        expected = safe_path_join(get_root_dir(), "scripts/shutdown.bat").replace(
            "\\", "/"
        )
        self.assertEqual(got, expected)

    def test_absolute_script_path_preserved(self):
        fake = {
            "script_list": [
                {"display_name": "原神", "script_path": "D:\\games\\BetterGI.exe"},
            ]
        }
        with (
            mock.patch("src.config.subscript._load_config_yml", return_value=fake),
            mock.patch("src.config.subscript.os.path.exists", return_value=True),
        ):
            got = get_script_path("BetterGI")
        self.assertEqual(got, "D:/games/BetterGI.exe")

    def test_missing_script_raises(self):
        fake = {"script_list": []}
        with (
            mock.patch("src.config.subscript._load_config_yml", return_value=fake),
            self.assertRaises(AssertionError),
        ):
            get_script_path("不存在")


class TestDefaultScriptEntry(unittest.TestCase):
    """测试 default_script_entry 字段补全"""

    def test_default_script_entry_has_all_fields(self):
        """default_script_entry 覆盖 config.yml 全部字段，核心字段用参数值"""
        entry = default_script_entry("崩坏3", "python", "C:/a/b.py")
        self.assertEqual(entry["display_name"], "崩坏3")
        self.assertEqual(entry["script_type"], "python")
        self.assertEqual(entry["script_path"], "C:/a/b.py")
        # 关键默认字段
        self.assertEqual(entry["script_process_name"], [])
        self.assertEqual(entry["kill_script_after_done"], True)
        self.assertEqual(entry["no_log_max_retries"], 3)
        # 与真实条目字段集合一致（无 run_timeout_seconds）
        expected_keys = {
            "display_name",
            "game_label",
            "script_type",
            "script_path",
            "script_process_name",
            "game_process_name",
            "launcher_mode",
            "check_done",
            "kill_script_after_done",
            "kill_game_after_done",
            "script_arguments",
            "notify_start",
            "notify_done",
            "notify_log_interval",
            "attach_direction",
            "no_log_timeout_seconds",
            "no_log_max_retries",
            "block",
        }
        self.assertEqual(set(entry.keys()), expected_keys)


class TestLoadGameConfig(unittest.TestCase):
    """测试 load_game_config：读取游戏路径配置文件（只读、不 assert 文件存在）。"""

    def test_root_missing_returns_none(self):
        """config.yml 中无此进程（根目录解析失败）→ None"""
        with mock.patch(
            "src.config.subscript.get_script_root_dir_soft", return_value=None
        ):
            got = load_game_config(
                "ok-ww", "data/apps/ok-ww/working/configs/devices.json"
            )
        self.assertIsNone(got)

    def test_config_file_missing_returns_none(self):
        """游戏配置文件不存在 → None（不 assert）"""
        with (
            mock.patch(
                "src.config.subscript.get_script_root_dir_soft",
                return_value="C:/root",
            ),
            mock.patch("src.config.subscript.os.path.exists", return_value=False),
        ):
            got = load_game_config(
                "ok-ww", "data/apps/ok-ww/working/configs/devices.json"
            )
        self.assertIsNone(got)

    def test_json_config_parsed(self):
        """JSON 游戏配置正确解析"""
        fake_path = "C:/root/data/apps/ok-ww/working/configs/devices.json"
        with (
            mock.patch(
                "src.config.subscript.get_script_root_dir_soft",
                return_value="C:/root",
            ),
            mock.patch("src.config.subscript.os.path.exists", return_value=True),
            mock.patch(
                "src.config.subscript.safe_path_join",
                return_value=fake_path,
            ),
            mock.patch(
                "builtins.open",
                mock.mock_open(read_data='{"pc_full_path": "D:/Game/game.exe"}'),
            ),
        ):
            got = load_game_config(
                "ok-ww", "data/apps/ok-ww/working/configs/devices.json"
            )
        self.assertEqual(got, {"pc_full_path": "D:/Game/game.exe"})

    def test_yaml_config_parsed(self):
        """YAML 游戏配置正确解析"""
        fake_path = "C:/root/config/01/game_account.yml"
        with (
            mock.patch(
                "src.config.subscript.get_script_root_dir_soft",
                return_value="C:/root",
            ),
            mock.patch("src.config.subscript.os.path.exists", return_value=True),
            mock.patch(
                "src.config.subscript.safe_path_join",
                return_value=fake_path,
            ),
            mock.patch(
                "builtins.open",
                mock.mock_open(read_data="game_path: D:/Game/game.exe\n"),
            ),
        ):
            got = load_game_config("OneDragon-Launcher", "config/01/game_account.yml")
        self.assertEqual(got, {"game_path": "D:/Game/game.exe"})


if __name__ == "__main__":
    unittest.main()
