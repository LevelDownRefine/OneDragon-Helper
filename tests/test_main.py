import importlib
import os
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


_TEMP_DIR = tempfile.TemporaryDirectory()
_SRC_DIR = Path(_TEMP_DIR.name) / "OneDragon-ScriptChainer" / "src"
_MODULE_DIR = _SRC_DIR / "one_dragon" / "utils"
_MODULE_DIR.mkdir(parents=True)
(_MODULE_DIR / "__init__.py").write_text("", encoding="utf-8")
(_MODULE_DIR.parent / "__init__.py").write_text("", encoding="utf-8")
(_SRC_DIR / "one_dragon" / "__init__.py").write_text("", encoding="utf-8")
(_MODULE_DIR / "os_utils.py").write_text(
    "import os\n"
    "import tempfile\n\n"
    "def get_path_under_work_dir(*parts):\n"
    "    return os.path.join(tempfile.gettempdir(), *parts)\n",
    encoding="utf-8",
)

sys.path.insert(0, str(_SRC_DIR))
try:
    sys.modules.pop("main", None)
    MAIN = importlib.import_module("main")
finally:
    sys.path.pop(0)


class MainTests(TestCase):
    def test_check_file_exists(self):
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_path = temp_file.name
        try:
            self.assertTrue(MAIN.check_file_exists(temp_path))
            os.unlink(temp_path)
            self.assertFalse(MAIN.check_file_exists(temp_path))
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_copy_config_copies_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir) / "config" / "script_chain"
            target_dir.mkdir(parents=True)

            def fake_get_path_under_work_dir(*parts):
                return str(Path(temp_dir).joinpath(*parts))

            with patch.object(MAIN, "get_path_under_work_dir", side_effect=fake_get_path_under_work_dir):
                MAIN.copy_config()

            copied_file = target_dir / "99.yml"
            self.assertTrue(copied_file.exists())
            expected_content = (Path(MAIN.BASE_DIR) / "99.yml").read_text(encoding="utf-8")
            self.assertEqual(copied_file.read_text(encoding="utf-8"), expected_content)

    def test_main_runs_launcher(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "config" / "script_chain"
            config_dir.mkdir(parents=True)
            src_dir = Path(temp_dir) / "src"
            src_dir.mkdir()

            def fake_get_path_under_work_dir(*parts):
                return str(Path(temp_dir).joinpath(*parts))

            with patch.object(MAIN, "get_path_under_work_dir", side_effect=fake_get_path_under_work_dir), \
                patch.object(MAIN, "copy_config") as copy_config, \
                patch.object(MAIN.subprocess, "run") as run:
                run.return_value.returncode = 0
                result = MAIN.main()

            copy_config.assert_called_once()
            run.assert_called_once_with(
                [
                    sys.executable,
                    "-m",
                    "script_chainer.win_exe.launcher",
                ],
                cwd=str(src_dir),
            )
            self.assertIs(result, run.return_value)
