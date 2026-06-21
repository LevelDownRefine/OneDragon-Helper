from unittest import TestCase
from unittest.mock import patch


import entry as ENTRY


class EntryTests(TestCase):
    def test_copy_config_when_file_missing(self):
        with (
            patch.object(ENTRY, "get_path_under_work_dir", return_value="/tmp/config/script_chain"),
            patch.object(ENTRY.os.path, "exists", return_value=False),
            patch.object(ENTRY.shutil, "copy") as copy,
        ):
            ENTRY.copy_config()

        copy.assert_called_once_with(
            ENTRY.BASE_DIR / "99.yml",
            "/tmp/config/script_chain",
        )

    def test_copy_config_skips_existing_file(self):
        with (
            patch.object(ENTRY, "get_path_under_work_dir", return_value="/tmp/config/script_chain"),
            patch.object(ENTRY.os.path, "exists", return_value=True),
            patch.object(ENTRY.shutil, "copy") as copy,
        ):
            ENTRY.copy_config()

        copy.assert_not_called()

    def test_copy_python_script_copies_missing_file(self):
        with (
            patch.object(ENTRY, "get_path_under_work_dir", return_value="/tmp/config/script_chain/scripts"),
            patch.object(ENTRY.os.path, "exists", return_value=False),
            patch.object(ENTRY.shutil, "copy") as copy,
        ):
            ENTRY.copy_python_script("entry.py")

        copy.assert_called_once_with(
            ENTRY.BASE_DIR / "entry.py",
            "/tmp/config/script_chain/scripts",
        )

    def test_copy_python_script_skips_existing_file(self):
        with (
            patch.object(ENTRY, "get_path_under_work_dir", return_value="/tmp/config/script_chain/scripts"),
            patch.object(ENTRY.os.path, "exists", return_value=True),
            patch.object(ENTRY.shutil, "copy") as copy,
        ):
            ENTRY.copy_python_script("entry.py")

        copy.assert_not_called()

    def test_main_runs_launcher(self):
        with (
            patch.object(ENTRY, "copy_config") as copy_config,
            patch.object(ENTRY, "get_path_under_work_dir", return_value="/work/src"),
            patch.object(ENTRY.subprocess, "run") as run,
        ):
            run.return_value.returncode = 0
            result = ENTRY.main()

        copy_config.assert_called_once_with()
        run.assert_called_once_with(
            [
                ENTRY.sys.executable,
                "-m",
                "script_chainer.win_exe.launcher",
            ],
            cwd="/work/src",
        )
        self.assertEqual(result, 0)
