"""脚本编辑保存与子脚本初始化的独立调用边界。"""

import unittest
from copy import deepcopy
from functools import cache
from unittest.mock import patch

from src.config import set_config
from src.service import app_service
from src.utils import utils_config


class TestScriptEdit(unittest.TestCase):
    def test_init_only_when_script_target_changes(self):
        previous = {
            "script_path": "C:/old/BetterGI.exe",
            "display_name": "原神",
        }
        for label, changes, expected_name in (
            ("unchanged", {}, None),
            ("display_name", {"display_name": "原神日常"}, None),
            ("arguments", {"script_arguments": "--test"}, None),
            ("game_path", {"game_path": "D:/YuanShen.exe"}, None),
            (
                "same_identity_new_path",
                {"script_path": "D:/new/BetterGI.exe"},
                "BetterGI",
            ),
            ("new_identity", {"script_path": "D:/MAA.exe"}, "MAA"),
        ):
            with self.subTest(label=label):
                current = {**previous, **changes}
                name = expected_name or "BetterGI"
                with (
                    patch.object(app_service, "get_script", return_value=current),
                    patch.object(app_service, "init_config") as init,
                ):
                    app_service.AppService().init_script_after_edit(previous, name)
                if expected_name:
                    init.assert_called_once_with(expected_name)
                else:
                    init.assert_not_called()

    def test_identity_change_without_path_change_initializes_new_identity(self):
        previous = {"script_path": "scripts/custom.py", "display_name": "旧脚本"}
        with (
            patch.object(
                app_service,
                "get_script",
                return_value={**previous, "display_name": "新脚本"},
            ),
            patch.object(app_service, "init_config") as init,
        ):
            app_service.AppService().init_script_after_edit(previous, "新脚本")
        init.assert_called_once_with("新脚本")

    def test_missing_saved_script_does_not_initialize(self):
        with (
            patch.object(app_service, "get_script", return_value=None),
            patch.object(app_service, "init_config") as init,
            self.assertRaisesRegex(AssertionError, "找不到已保存脚本"),
        ):
            app_service.AppService().init_script_after_edit({}, "missing")
        init.assert_not_called()

    def test_edit_flow_preserves_native_config_until_path_changes(self):
        """真实保存调用链：普通保存不读写原生配置，换目录后显式对齐一次。"""
        script = {
            "script_path": "C:/old/BetterGI.exe",
            "display_name": "原神",
            "game_process_name": "YuanShen.exe",
        }
        helper_config = {"script_list": [script]}
        template = {"task": {"enabled": True}}
        factory = cache(set_config.GenshinConfig)
        service = app_service.AppService()
        with (
            patch.dict(set_config._CONFIGS, {"BetterGI": factory}, clear=True),
            patch.object(utils_config, "load_config", return_value=helper_config),
            patch.object(utils_config, "save_config") as helper_write,
            patch.object(utils_config, "save_weekly") as weekly_write,
            patch.object(
                set_config, "load_config", return_value=template
            ) as native_read,
            patch.object(set_config, "load_template", return_value=template),
            patch.object(set_config, "save_config") as native_write,
        ):
            set_config.ensure_config("BetterGI")
            native_read.reset_mock()
            for label, changes, timeouts in (
                ("unchanged", {}, [60] * 7),
                ("timeout_only", {}, [90] * 7),
                ("arguments_only", {"script_arguments": "--test"}, [90] * 7),
            ):
                with self.subTest(label=label), self.assertNoLogs(set_config.logger):
                    previous = deepcopy(script)
                    name = service.update_script("BetterGI", "原神", changes, timeouts)
                    service.init_script_after_edit(previous, name)
                    native_read.assert_not_called()
                    native_write.assert_not_called()

            previous = deepcopy(script)
            name = service.update_script(
                "BetterGI", "原神", {"script_path": "D:/new/BetterGI.exe"}, [90] * 7
            )
            # 保存路径仍不隐式对齐；编辑流程显式调用后才检查模板。
            native_read.assert_not_called()
            with self.assertLogs(set_config.logger, level="INFO") as logs:
                service.init_script_after_edit(previous, name)
            self.assertEqual(len(logs.records), 1)
            native_read.assert_called_once_with(
                "BetterGI", "User/OneDragon/默认配置.json"
            )
            native_write.assert_not_called()
            self.assertEqual(helper_write.call_count, 4)
            self.assertEqual(weekly_write.call_count, 4)
