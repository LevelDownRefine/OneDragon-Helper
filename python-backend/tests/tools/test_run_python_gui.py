"""以真实子进程验证工作树启动不受其他源码路径影响。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import run_python_gui


class TestPythonGuiLauncher(unittest.TestCase):
    def test_current_checkout_overrides_stale_package_paths_and_preserves_arguments(
        self,
    ):
        base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        root = base / "工作树 空间"
        stale = base / "other-checkout"
        gui = root / "python-gui/src/gui"
        backend = root / "python-backend/src"
        for package in [gui, backend, stale / "gui", stale / "src"]:
            package.mkdir(parents=True)
            (package / "__init__.py").touch()
        (stale / "gui/launcher.py").write_text(
            'raise RuntimeError("loaded wrong GUI")', encoding="utf-8"
        )
        (stale / "src/current.py").write_text('MARKER = "wrong"', encoding="utf-8")
        (backend / "current.py").write_text('MARKER = "current"', encoding="utf-8")
        (gui / "launcher.py").write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "from src.current import MARKER\n"
            "Path(sys.argv[1]).write_text(json.dumps({\n"
            "    'marker': MARKER, 'cwd': str(Path.cwd()),\n"
            "    'args': sys.argv[2:], 'utf8': os.environ['PYTHONUTF8'],\n"
            "}), encoding='utf-8')\n"
            "sys.exit(7)\n",
            encoding="utf-8",
        )
        result = base / "result.json"
        with (
            patch.object(run_python_gui, "PROJECT_ROOT", root),
            patch.dict(os.environ, {"PYTHONPATH": str(stale)}),
        ):
            code = run_python_gui.main([str(result), "含 空格参数", "--version"])
        self.assertEqual(code, 7)
        self.assertEqual(
            json.loads(result.read_text(encoding="utf-8")),
            {
                "marker": "current",
                "cwd": str(root),
                "args": ["含 空格参数", "--version"],
                "utf8": "1",
            },
        )
