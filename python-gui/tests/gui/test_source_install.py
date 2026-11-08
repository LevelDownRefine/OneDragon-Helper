"""源码安装交互与后台结果衔接。"""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtTest import QTest

from gui.controllers.source_install import SourceInstallController
from tests.gui.helpers import get_app


class SourceInstallTests(unittest.TestCase):
    def setUp(self):
        get_app()
        self.service = Mock()
        self.toast = Mock()
        self.reload = Mock()
        self.controller = SourceInstallController(
            self.service, None, self.toast, self.reload
        )

    def tearDown(self):
        self.controller._close()
        self.controller.deleteLater()
        get_app().processEvents()

    def test_direct_install_registers_and_refreshes(self):
        definition = {
            "display_name": "测试",
            "entry": "main.py",
            "manual_arguments": [],
            "run_arguments": ["--run"],
        }
        self.service.source_catalog.return_value = {"example": definition}
        self.service.start_catalog_source_install.return_value = {"id": "job"}
        self.service.jobs.poll.return_value = {
            "state": "succeeded",
            "result": {"source": str(Path.cwd())},
        }
        with (
            patch(
                "gui.controllers.source_install.QInputDialog.getItem",
                return_value=("测试", True),
            ),
            patch(
                "gui.controllers.source_install.QFileDialog.getExistingDirectory",
                return_value=str(Path.cwd()),
            ),
        ):
            self.controller.start()
            QTest.qWait(500)
        self.service.start_catalog_source_install.assert_called_once_with(
            "example", str(Path.cwd())
        )
        self.service.register_source_application.assert_called_once_with(
            application_id="example",
            display_name="测试",
            source_root=str(Path.cwd()),
            script_path=str(Path.cwd() / "main.py"),
            manual_arguments=[],
            run_arguments=["--run"],
        )
        self.reload.assert_called_once()
        self.assertIsNone(self.controller.dialog)

    def test_failed_install_is_reported_without_registration(self):
        self.controller._failure(ValueError("安装失败"))
        self.toast.assert_called_once_with("安装失败")
        self.service.register_source_application.assert_not_called()
