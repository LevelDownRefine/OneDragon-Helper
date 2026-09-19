"""测试 ConfigWarmer：启动后空闲逐脚本预热，失败不中断、全部完成发 finished。"""

import unittest

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src.gui.config_warmer import ConfigWarmer


class TestConfigWarmer(unittest.TestCase):
    def _run_warmer(self, warmer: ConfigWarmer) -> None:
        app = QApplication.instance() or QApplication([])
        warmer.finished.connect(app.quit)
        watchdog = QTimer(app)
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(app.quit)
        watchdog.start(3000)
        warmer.start(0)
        app.exec()

    def test_warmer_warms_all_scripts_once(self):
        warmed = []
        names = ["a", "b", "c", "d"]
        self._run_warmer(ConfigWarmer(names, warmed.append))
        self.assertEqual(warmed, names)

    def test_warmer_continues_after_failure(self):
        warmed = []

        def flaky(name: str) -> None:
            if name == "b":
                raise RuntimeError("boom")
            warmed.append(name)

        self._run_warmer(ConfigWarmer(["a", "b", "c"], flaky))
        self.assertEqual(warmed, ["a", "c"])

    def test_warmer_finished_immediately_when_empty(self):
        QApplication.instance() or QApplication([])
        finished = []
        warmer = ConfigWarmer([], lambda n: None)
        warmer.finished.connect(lambda: finished.append(True))
        warmer.start(0)
        self.assertTrue(finished)


if __name__ == "__main__":
    unittest.main()
