"""外观装配回归：懒加载、跨入口共享单例与自定义脚本边界。"""

import unittest
from functools import cache
from unittest.mock import Mock, create_autospec, patch

from src.config.set_config import _CONFIGS, ScriptConfig, ScriptConfigFacade
from src.service.app_service import AppService


class TestScriptConfigFacade(unittest.TestCase):
    def test_constructing_and_listing_do_not_initialize_adapters(self):
        factory = Mock()
        with patch.dict(_CONFIGS, {"sample": factory}, clear=True):
            facade = ScriptConfigFacade()
            service = AppService()
            self.assertEqual(facade.get_registered_script_names(), ["sample"])
            self.assertEqual(service.get_registered_script_names(), ["sample"])
            self.assertTrue(service.is_adapted("sample"))
            self.assertFalse(service.is_adapted("custom"))
        factory.assert_not_called()

    def test_warmup_and_separate_facades_share_the_registered_singleton(self):
        adapter = Mock(spec=ScriptConfig)
        adapter._read_daily_tasks.return_value = []
        factory = Mock(return_value=adapter)
        with patch.dict(_CONFIGS, {"sample": cache(factory)}, clear=True):
            service = AppService()
            facade = ScriptConfigFacade()
            service.warm_config("sample")
            facade.ensure_config("sample")
            self.assertEqual(service.get_daily_readback("sample"), [])
            facade.set_daily_task("sample", "daily", "task", 3)
            facade.init_config("sample")
        factory.assert_called_once_with()
        adapter.set_daily_task.assert_called_once_with("daily", "task", 3)
        # 预热只调用工厂；显式 init_config 才额外触发强制对齐。
        adapter._init_config.assert_called_once_with()

    def test_empty_injected_registry_does_not_fall_back_to_builtins(self):
        facade = ScriptConfigFacade({})
        self.assertEqual(facade.get_registered_script_names(), [])
        self.assertEqual(facade.iter_backup_paths(), {})
        self.assertFalse(facade.is_adapted("BetterGI"))
        facade.init_config_all()

    def test_custom_script_queries_remain_optional(self):
        factory = Mock()
        facade = ScriptConfigFacade({"sample": factory})
        self.assertEqual(facade.get_daily_readback("custom"), [])
        self.assertIsNone(facade.get_task_lists("custom", "daily", {}))
        self.assertIsNone(facade.get_game_exe_path("custom"))
        self.assertEqual(facade.get_background_rel_path("custom"), "")
        self.assertEqual(facade.get_game_path_keys("custom", "config.json"), ())
        facade.ensure_config("custom")
        facade.init_config("custom")
        facade.set_daily_task("custom", "daily", "task")
        factory.assert_not_called()

    def test_operations_requiring_an_adapter_reject_custom_scripts(self):
        facade = ScriptConfigFacade({})
        with self.assertRaisesRegex(AssertionError, "未适配脚本: custom"):
            facade.get_config_path("custom")
        with self.assertRaisesRegex(AssertionError, "未适配脚本: custom"):
            facade.set_daily_enabled("custom", "daily", False)

    def test_unselected_task_does_not_initialize_adapter(self):
        factory = Mock()
        facade = ScriptConfigFacade({"sample": factory})
        for task in (None, "", "未选择"):
            with self.subTest(task=task):
                facade.set_daily_task("sample", "daily", task)
        factory.assert_not_called()


class TestAppServiceConfigFacade(unittest.TestCase):
    def test_gui_reads_use_the_injected_facade(self):
        facade = create_autospec(ScriptConfigFacade, instance=True)
        service = AppService(script_config=facade)
        for method, result in (
            ("get_daily_readback", [{"name": "daily", "task": "task"}]),
            ("get_game_exe_path", "game.exe"),
            ("get_background_rel_path", "assets/bg.jpg"),
            ("is_adapted", True),
        ):
            with self.subTest(method=method):
                delegate = getattr(facade, method)
                delegate.return_value = result
                self.assertEqual(getattr(service, method)("sample"), result)
                delegate.assert_called_once_with("sample")

    def test_warmup_and_daily_edits_use_the_injected_facade(self):
        facade = create_autospec(ScriptConfigFacade, instance=True)
        service = AppService(script_config=facade)
        service.warm_config("sample")
        service.set_script_daily_task("sample", "daily", "task", 2)
        service.set_script_daily_enabled("sample", "daily", False)
        facade.ensure_config.assert_called_once_with("sample")
        facade.set_daily_task.assert_called_once_with(
            "sample", daily_display_name="daily", task_name="task", sequence=2
        )
        facade.set_daily_enabled.assert_called_once_with("sample", "daily", False)
