import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from src.config.set_config import get_game_path_keys
from src.service import backup_service
from src.service.chain_gen import generate_chain_config
from src.service.source_app_service import (
    configure_source_application,
    format_arguments,
    install_catalog_application,
    install_source_application,
    parse_arguments,
    register_source_application,
)
from src.utils.utils_io import load_data
from src.utils.utils_job import InvalidJob
from src.utils.utils_sub_config import (
    get_script_path,
    get_script_root_dir,
    get_sub_config_path,
    resolve_log_path,
)


class SourceAppServiceTests(unittest.TestCase):
    def test_argument_round_trip(self):
        arguments = ["--name", "hello world", "", 'quote"inside', "C:/space path/"]
        self.assertEqual(parse_arguments(format_arguments(arguments)), arguments)

    def test_completed_install_can_be_registered_after_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "example"
            source = target / "app"
            executable = (
                source
                / ".venv"
                / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            )
            executable.parent.mkdir(parents=True)
            executable.touch()
            identity = {
                "repository": "https://example.com/a.git",
                "revision": "v1",
                "python_version": "3.12",
                "requirements": "requirements.txt",
            }
            (target / "install.json").write_text(
                json.dumps({"application": identity, "complete": True}),
                encoding="utf-8",
            )
            with patch(
                "src.service.source_app_service.install",
                side_effect=FileExistsError("installed"),
            ):
                result = install_source_application(
                    "example",
                    identity["repository"],
                    "v1",
                    "3.12",
                    "requirements.txt",
                    directory,
                )
                self.assertEqual(result["source"], str(source))
                with self.assertRaises(FileExistsError):
                    install_source_application(
                        "example",
                        identity["repository"],
                        "v2",
                        "3.12",
                        "requirements.txt",
                        directory,
                    )

    def test_configure_updates_entry_and_preserves_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "alternate.py"
            script.touch()
            executable = "Scripts/python.exe" if os.name == "nt" else "bin/python"
            interpreter = root / ".venv" / executable
            interpreter.parent.mkdir(parents=True)
            interpreter.touch()
            entry = {
                "display_name": "鸣潮",
                "script_id": "ok-ww",
                "script_path": str(root / "main.py"),
                "source_root": str(root),
                "unrelated": "keep",
            }
            config = {"script_list": [entry]}
            with (
                patch("src.utils.utils_config.load_config", return_value=config),
                patch("src.utils.utils_config.save_config") as save,
                patch("src.config.set_config.invalidate_config") as invalidate,
            ):
                configure_source_application(
                    "ok-ww", str(script), ["--gui"], ["-t", "1", "-e"]
                )
            self.assertEqual(entry["script_path"], str(script))
            self.assertEqual(entry["source_manual_arguments"], ["--gui"])
            self.assertEqual(entry["source_arguments"], ["-t", "1", "-e"])
            self.assertEqual(entry["unrelated"], "keep")
            save.assert_called_once_with(config)
            invalidate.assert_called_once_with("ok-ww")

    def test_catalog_install_selects_latest_tag_and_checks_path(self):
        definition = {
            "repository": "https://example.org/repo.git",
            "release_api": "https://example.org/latest",
            "python_version": "3.12",
            "requirements": "requirements.txt",
            "ascii_path": True,
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "src.service.source_app_service.source_catalog",
                return_value={"ok-ww": definition},
            ),
            patch("requests.get") as request,
            patch(
                "src.service.source_app_service.install_source_application",
                return_value={"ok": True},
            ) as install,
        ):
            request.return_value.json.return_value = {"tag_name": "v2"}
            self.assertEqual(
                install_catalog_application("ok-ww", directory), {"ok": True}
            )
            self.assertEqual(install.call_args.args[2], "v2")
            with self.assertRaises(InvalidJob):
                install_catalog_application("ok-ww", str(Path(directory) / "中文"))

    def test_existing_identity_requires_explicit_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "main.py"
            script.touch()
            executable = "Scripts/python.exe" if os.name == "nt" else "bin/python"
            interpreter = root / ".venv" / executable
            interpreter.parent.mkdir(parents=True)
            interpreter.touch()
            existing = {"display_name": "鸣潮", "script_path": "ok-ww.exe"}
            config = {"script_list": [existing]}
            with (
                patch("src.utils.utils_config.load_config", return_value=config),
                patch("src.utils.utils_config.save_config") as save,
                patch("src.utils.utils_weekly.ensure_weekly_entry"),
            ):
                with self.assertRaises(InvalidJob):
                    register_source_application(
                        "ok-ww", "鸣潮", str(root), str(script), [], []
                    )
                save.assert_not_called()
                self.assertIs(config["script_list"][0], existing)
                register_source_application(
                    "ok-ww", "鸣潮", str(root), str(script), [], [], True
                )
            self.assertEqual(config["script_list"][0]["source_root"], str(root))

    def test_register_keeps_stable_identity_and_separate_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "main.py"
            script.touch()
            executable = "Scripts/python.exe" if os.name == "nt" else "bin/python"
            interpreter = root / ".venv" / executable
            interpreter.parent.mkdir(parents=True)
            interpreter.touch()
            config = {"script_list": []}
            with (
                patch("src.utils.utils_config.load_config", return_value=config),
                patch("src.utils.utils_config.save_config") as save,
                patch("src.utils.utils_weekly.ensure_weekly_entry") as weekly,
            ):
                result = register_source_application(
                    "ok-ww",
                    "鸣潮",
                    str(root),
                    str(script),
                    ["--help"],
                    ["-t", "1", "-e"],
                )
            self.assertEqual(result["script_name"], "ok-ww")
            entry = config["script_list"][0]
            self.assertEqual(entry["script_id"], "ok-ww")
            self.assertEqual(entry["source_manual_arguments"], ["--help"])
            self.assertEqual(entry["source_arguments"], ["-t", "1", "-e"])
            save.assert_called_once_with(config)
            weekly.assert_called_once_with("ok-ww")

    def test_source_config_and_log_use_source_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / "nested" / "main.py"
            entry.parent.mkdir()
            entry.touch()
            script = {
                "display_name": "鸣潮",
                "script_id": "ok-ww",
                "script_path": str(entry),
                "source_root": str(root),
            }
            config = root / "config.yml"
            config.touch()
            with (
                patch(
                    "src.utils.utils_sub_config._load_config_yml",
                    return_value={"script_list": [script]},
                ),
                patch(
                    "src.utils.utils_sub_config.get_config_yml_path_under_root",
                    return_value=str(config),
                ),
            ):
                self.assertEqual(Path(get_script_path("ok-ww")), entry)
                self.assertEqual(Path(get_script_root_dir("ok-ww")), root)
                self.assertEqual(
                    Path(
                        get_sub_config_path(
                            "ok-ww", "data/apps/ok-ww/working/configs/DailyTask.json"
                        )
                    ),
                    root / "configs" / "DailyTask.json",
                )
                self.assertEqual(
                    resolve_log_path(script), root / "logs" / "ok-script.log"
                )
                self.assertEqual(
                    get_game_path_keys("ok-ww", "configs/devices.json"),
                    ("pc_full_path",),
                )
                config_dir = root / "configs"
                config_dir.mkdir()
                (config_dir / "DailyTask.json").write_text("{}", encoding="utf-8")
                backup_dir = root / "backups"
                backup_dir.mkdir()
                with (
                    patch.object(
                        backup_service,
                        "iter_backup_paths",
                        return_value={"ok-ww": ("data/apps/ok-ww/working/configs",)},
                    ),
                    patch.object(
                        backup_service,
                        "get_path_under_root",
                        return_value=str(backup_dir),
                    ),
                ):
                    result = backup_service.create_backup()
                with zipfile.ZipFile(result["path"]) as archive:
                    self.assertIn(
                        "scripts/ok-ww/configs/DailyTask.json", archive.namelist()
                    )

    def test_chain_uses_source_interpreter_and_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "sub" / "main.py"
            script.parent.mkdir()
            script.touch()
            executable = "Scripts/python.exe" if os.name == "nt" else "bin/python"
            interpreter = root / ".venv" / executable
            interpreter.parent.mkdir(parents=True)
            interpreter.touch()
            output = str(root / "chain.yml")
            entry = {
                "display_name": "Example",
                "script_path": str(script),
                "source_root": str(root),
                "source_arguments": ["hello world"],
            }
            generate_chain_config(
                {"script_list": [entry]}, {"Example"}, out_path=output
            )
            chain = load_data(output, file_format="yaml")
            generated = chain["script_list"][0]
            self.assertEqual(generated["execution_program"], str(interpreter))
            self.assertEqual(generated["execution_args"], [str(script), "hello world"])
            self.assertEqual(generated["execution_cwd"], str(root))
            self.assertFalse(generated["launcher_mode"])

    def test_install_uses_application_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "ok-ww"
            with patch(
                "src.service.source_app_service.install", return_value=target / "app"
            ) as mock_install:
                result = install_source_application(
                    "ok-ww",
                    "https://example.org/repo.git",
                    "v1",
                    "3.12",
                    "requirements.txt",
                    directory,
                )
            self.assertEqual(result["source"], str(target / "app"))
            self.assertEqual(mock_install.call_args.args[1], target)

    def test_rejects_invalid_application_id(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(InvalidJob):
            install_source_application(
                "../escape", "repo", "v1", "3.12", "requirements.txt", directory
            )
