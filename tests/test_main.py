import importlib
import sys
import types
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


def _install_os_utils_stub():
    one_dragon = types.ModuleType("one_dragon")
    one_dragon.__path__ = []
    utils = types.ModuleType("one_dragon.utils")
    utils.__path__ = []
    os_utils = types.ModuleType("one_dragon.utils.os_utils")
    os_utils.get_path_under_work_dir = lambda *parts: str(Path("/work").joinpath(*parts))

    sys.modules["one_dragon"] = one_dragon
    sys.modules["one_dragon.utils"] = utils
    sys.modules["one_dragon.utils.os_utils"] = os_utils


_install_os_utils_stub()
sys.modules.pop("main", None)
MAIN = importlib.import_module("main")
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in ("one_dragon", "one_dragon.utils", "one_dragon.utils.os_utils")}


class MainTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        for name, module in _ORIGINAL_MODULES.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_teardown_class_restores_stub_modules(self):
        backups = {name: sys.modules.get(name) for name in _ORIGINAL_MODULES}
        try:
            for name in _ORIGINAL_MODULES:
                sys.modules[name] = types.ModuleType(f"{name}.sentinel")

            MainTests.tearDownClass()

            for name, module in _ORIGINAL_MODULES.items():
                self.assertIs(sys.modules.get(name), module)
        finally:
            for name, module in backups.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    def test_copy_config_when_file_missing(self):
        with (
            patch.object(MAIN, "get_path_under_work_dir", return_value="/tmp/config/script_chain"),
            patch.object(MAIN.os.path, "exists", return_value=False),
            patch.object(MAIN.shutil, "copy") as copy,
        ):
            MAIN.copy_config()

        copy.assert_called_once_with(
            str(Path(MAIN.BASE_DIR) / "99.yml"),
            "/tmp/config/script_chain",
        )

    def test_copy_config_skips_existing_file(self):
        with (
            patch.object(MAIN, "get_path_under_work_dir", return_value="/tmp/config/script_chain"),
            patch.object(MAIN.os.path, "exists", return_value=True),
            patch.object(MAIN.shutil, "copy") as copy,
        ):
            MAIN.copy_config()

        copy.assert_not_called()

    def test_copy_python_script_copies_missing_file(self):
        with (
            patch.object(MAIN, "get_path_under_work_dir", return_value="/tmp/config/script_chain/scripts"),
            patch.object(MAIN.os.path, "exists", return_value=False),
            patch.object(MAIN.shutil, "copy") as copy,
        ):
            MAIN.copy_python_script("main.py")

        copy.assert_called_once_with(
            str(Path(MAIN.BASE_DIR) / "main.py"),
            "/tmp/config/script_chain/scripts",
        )

    def test_copy_python_script_skips_existing_file(self):
        with (
            patch.object(MAIN, "get_path_under_work_dir", return_value="/tmp/config/script_chain/scripts"),
            patch.object(MAIN.os.path, "exists", return_value=True),
            patch.object(MAIN.shutil, "copy") as copy,
        ):
            MAIN.copy_python_script("main.py")

        copy.assert_not_called()

    def test_main_runs_launcher(self):
        with (
            patch.object(MAIN, "copy_config") as copy_config,
            patch.object(MAIN, "get_path_under_work_dir", return_value="/work/src"),
            patch.object(MAIN.subprocess, "run") as run,
        ):
            run.return_value.returncode = 0
            result = MAIN.main()

        copy_config.assert_called_once_with()
        run.assert_called_once_with(
            [
                sys.executable,
                "-m",
                "script_chainer.win_exe.launcher",
            ],
            cwd="/work/src",
        )
        self.assertEqual(result, 0)
