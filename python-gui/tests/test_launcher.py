"""测试 gui/launcher.py：首次初始化流程"""

import os
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import ANY, Mock, patch

# 在导入 PySide6 相关模块之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui import launcher
from src.config.generate_config import config_workflow


class TestInitConfig(unittest.TestCase):
    """测试首次初始化流程（config_workflow）"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    @patch("src.config.generate_config.generate_weekly_from_example")
    @patch("src.config.generate_config.generate_schedule_from_example")
    @patch("src.config.generate_config.generate_config_from_example")
    @patch("src.config.generate_config.os.path.exists", return_value=False)
    @patch("src.config.generate_config.get_config_yml_path_under_root")
    @patch("src.config.generate_config.get_schedule_yml_path_under_root")
    @patch("src.config.generate_config.get_weekly_yml_path_under_root")
    def test_config_workflow(
        self,
        mock_weekly_path,
        mock_schedule_path,
        mock_config_path,
        mock_exists,
        mock_generate_config,
        mock_generate_schedule,
        mock_generate_weekly,
    ):
        # 模拟首次运行：config.yml / schedule.yml / weekly.yml 均不存在，触发从模板生成
        mock_config_path.return_value = os.path.join(self.temp_dir.name, "config.yml")
        mock_schedule_path.return_value = os.path.join(
            self.temp_dir.name, "schedule.yml"
        )
        mock_weekly_path.return_value = os.path.join(self.temp_dir.name, "weekly.yml")
        with patch("src.config.set_config.ArknightsConfig._init_config") as init:
            config_workflow()

        # 首次运行时，config.yml / schedule.yml / weekly.yml 均应从模板生成
        mock_generate_config.assert_called_once()
        mock_generate_schedule.assert_called_once()
        mock_generate_weekly.assert_called_once()
        # 启动不再急切对齐各脚本 config；对齐收口到 ScriptConfig 构造时（懒加载）
        init.assert_not_called()


class TestMainStartupOrder(unittest.TestCase):
    def test_backend_logging_precedes_config_generation(self):
        order = []
        with (
            patch.object(
                launcher,
                "setup_logging",
                side_effect=lambda **_: order.append("logging"),
            ),
            patch.object(
                launcher,
                "install_crash_hooks",
                side_effect=lambda: order.append("hooks"),
            ),
            patch(
                "src.config.generate_config.config_workflow",
                side_effect=lambda: order.append("config"),
            ),
            patch("src.cli.run_cli", return_value=0),
            patch.object(sys, "argv", ["gui", "--version"]),
            self.assertRaises(SystemExit),
        ):
            launcher.main()
        self.assertEqual(order, ["logging", "hooks", "config"])

    def test_gui_does_not_generate_business_config(self):
        with (
            patch.object(launcher, "setup_logging"),
            patch.object(launcher, "install_crash_hooks"),
            patch("src.config.generate_config.config_workflow") as workflow,
            patch.object(launcher, "_launch_qml") as window,
            patch.object(sys, "argv", ["gui"]),
        ):
            launcher.main()
        workflow.assert_not_called()
        window.assert_called_once_with(skip_auto_launch=False)


class TestMainLogRole(unittest.TestCase):
    def test_run_entries_log_to_plan_file(self):
        for arguments, role in (
            ([], "gui"),
            (["--dump-config"], "gui"),
            (["--run-daily"], "plan"),
            (["--schedule-run", "now"], "plan"),
            (["--run-chain", "plan.yml"], "plan"),
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(launcher, "setup_logging") as setup,
                patch.object(launcher, "install_crash_hooks"),
                patch("src.config.generate_config.config_workflow"),
                patch("src.cli.run_cli", return_value=0),
                patch.object(launcher, "_launch_qml", side_effect=SystemExit(0)),
                patch.object(sys, "argv", ["gui", *arguments]),
                self.assertRaises(SystemExit),
            ):
                launcher.main()
            setup.assert_called_once_with(role=role)


class TestStartupTimer(unittest.TestCase):
    def test_main_resets_baseline(self):
        launcher._STARTUP_T0 -= 3600
        with (
            patch.object(launcher, "setup_logging"),
            patch.object(launcher, "install_crash_hooks"),
            patch.object(launcher, "_launch_qml"),
            patch.object(sys, "argv", ["gui"]),
        ):
            launcher.main()
        self.assertLess(time.perf_counter() - launcher._STARTUP_T0, 1)


class TestUpdateRestart(unittest.TestCase):
    def test_update_restart_skips_task_countdown_only_for_this_launch(self):
        for skip in (False, True):
            with self.subTest(skip=skip), ExitStack() as stack:
                for name in (
                    "setup_logging",
                    "install_crash_hooks",
                    "_clear_qml_cache",
                    "_install_qt_message_logger",
                    "QApplication",
                    "qmlRegisterSingletonInstance",
                    "install_file_drop",
                ):
                    stack.enter_context(patch.object(launcher, name))
                stack.enter_context(patch.object(sys, "frozen", False, create=True))
                stack.enter_context(
                    patch.object(
                        sys, "argv", ["gui", *(["--after-update"] if skip else [])]
                    )
                )
                engine = stack.enter_context(
                    patch.object(launcher, "QQmlApplicationEngine")
                )
                engine.return_value.rootObjects.return_value = [Mock()]
                client = stack.enter_context(patch("gui.cli_client.CliClient"))
                client.return_value.running = False
                bridge = stack.enter_context(patch.object(launcher, "QmlBridge"))
                timer = stack.enter_context(patch.object(launcher, "QTimer"))
                with self.assertRaises(SystemExit):
                    launcher.main()
                self.assertEqual(
                    bridge.return_value.maybe_auto_launch.call_count, int(not skip)
                )
                bridge.assert_called_once_with(
                    cli_client=client.return_value, cli_client_factory=ANY
                )
                assert "cli_client_factory" in bridge.call_args.kwargs
                self.assertIs(
                    bridge.call_args.kwargs["cli_client_factory"](), client.return_value
                )
                if skip:
                    timer.singleShot.assert_called_once()
                    timer.singleShot.call_args.args[1]()
                    bridge.return_value.toastRequested.emit.assert_called_once_with(
                        "更新完成，欢迎回来"
                    )
                else:
                    timer.singleShot.assert_not_called()

    def test_shutdown_confirmation_does_not_initialize_or_launch_scripts(self):
        for confirmed, code in ((True, 42), (False, 0)):
            with (
                self.subTest(confirmed=confirmed),
                patch.object(sys, "argv", ["gui", "--shutdown-confirm", "45"]),
                patch.object(launcher, "QApplication"),
                patch("src.config.generate_config.config_workflow") as workflow,
                patch.object(launcher, "_launch_qml") as window,
                patch(
                    "gui.shutdown_dialog.confirm_shutdown", return_value=confirmed
                ) as confirm,
                self.assertRaises(SystemExit) as result,
            ):
                launcher.main()
            self.assertEqual(result.exception.code, code)
            confirm.assert_called_once_with(45)
            workflow.assert_not_called()
            window.assert_not_called()


class TestCliBackendRouting(unittest.TestCase):
    def _launch(self, root, *, frozen):
        with ExitStack() as stack:
            for name in (
                "_clear_qml_cache",
                "_install_qt_message_logger",
                "QApplication",
                "QTimer",
                "qmlRegisterSingletonInstance",
                "install_file_drop",
            ):
                stack.enter_context(patch.object(launcher, name))
            stack.enter_context(patch.object(sys, "frozen", frozen, create=True))
            stack.enter_context(patch("src.utils.get_root_dir", return_value=str(root)))
            stack.enter_context(
                patch.object(launcher.os.path, "isfile", return_value=True)
            )
            stack.enter_context(
                patch.object(
                    launcher, "resolve_script_path", return_value=str(root / "main.qml")
                )
            )
            engine = stack.enter_context(
                patch.object(launcher, "QQmlApplicationEngine")
            )
            engine.return_value.rootObjects.return_value = [Mock()]
            client = stack.enter_context(patch("gui.cli_client.CliClient"))
            client.return_value.running = False
            bridge = stack.enter_context(patch.object(launcher, "QmlBridge"))
            warning = stack.enter_context(patch("gui.dialogs.show_warning"))
            with self.assertRaises(SystemExit) as result:
                launcher._launch_qml(skip_auto_launch=True)
            return client, bridge, warning, result.exception.code

    def test_source_uses_python_module_without_cli_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client, bridge, warning, _ = self._launch(root, frozen=False)
        self.assertEqual(
            client.call_args.args[:3],
            (
                sys.executable,
                ["-m", "src.headless", "serve", "--stdio"],
                str(root / "python-backend"),
            ),
        )
        assert "cli_client" in bridge.call_args.kwargs
        self.assertIs(bridge.call_args.kwargs["cli_client"], client.return_value)
        warning.assert_not_called()

    def test_frozen_uses_bundled_cli(self):
        from src.update import CLI_EXE, QT_CLI_EXE

        for relative in (CLI_EXE, QT_CLI_EXE):
            with (
                self.subTest(relative=relative),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                executable = root / relative
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.touch()
                client, bridge, warning, _ = self._launch(root, frozen=True)
            self.assertEqual(
                client.call_args.args[:3],
                (str(executable), ["serve", "--stdio"], str(root)),
            )
            assert "cli_client" in bridge.call_args.kwargs
            self.assertIs(bridge.call_args.kwargs["cli_client"], client.return_value)
            warning.assert_not_called()

    def test_frozen_without_cli_fails_before_constructing_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            client, bridge, warning, code = self._launch(Path(directory), frozen=True)
        client.assert_not_called()
        bridge.assert_not_called()
        self.assertEqual(code, 2)
        warning.assert_called_once()
        self.assertIn("发布包不完整", warning.call_args.args[1])


class TestQtMessageLogger(unittest.TestCase):
    """_install_qt_message_logger：Qt/QML 告警路由到 logging（windowed exe 无 stderr）。"""

    def test_qt_warning_routed_to_logger(self):
        from PySide6.QtCore import qInstallMessageHandler, qWarning

        previous = qInstallMessageHandler(None)
        self.addCleanup(qInstallMessageHandler, previous)
        launcher._install_qt_message_logger()
        with self.assertLogs("gui.launcher", level="WARNING") as captured:
            qWarning("test-qml-warning")
        self.assertTrue(
            any("[qt] test-qml-warning" in line for line in captured.output)
        )


if __name__ == "__main__":
    unittest.main()
