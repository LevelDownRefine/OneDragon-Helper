"""隔离配置与无 Qt 导入断言下运行真正的 Python CLI。"""

import importlib.abc
import runpy
import sys
from pathlib import Path

from tools.run_rust_gui import prepare_demo


class NoGui(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in ("PySide6", "shiboken6") or fullname.startswith(
            "src.gui"
        ):
            raise AssertionError("CLI 加载了 GUI: " + fullname)


root = Path(sys.argv[1])
prepare_demo(root)
sys.path.insert(0, str(root))
sys.meta_path.insert(0, NoGui())
sys.argv = ["headless", "serve", "--stdio"]
runpy.run_module("src.headless", run_name="__main__")
