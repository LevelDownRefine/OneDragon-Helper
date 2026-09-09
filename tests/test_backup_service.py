"""普通 ZIP 配置迁移：真实临时文件覆盖字节往返、换机定位与失败边界。"""

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from src.config import set_config
from src.service import backup_service as backup
from src.utils.utils_yaml import dump_yaml_str, load_yaml_str


class TestBackupService(unittest.TestCase):
    def test_preserves_paths_for_every_adapter(self):
        """真实适配器声明覆盖 JSON、YAML 和嵌套字段，其他字段来自备份。"""
        for script_name, cls in set_config._CONFIGS.items():
            with self.subTest(script=script_name):
                self.roots[script_name] = str(self.root / script_name)
                rel, keys = cls._game_config_rel_path, cls._game_path_keys
                old, current = {"task": 1}, {"task": 99}
                for data, value in ((old, "old-machine"), (current, "this-machine")):
                    node = data
                    for key in keys[:-1]:
                        node[key] = {}
                        node = node[key]
                    node[keys[-1]] = value
                is_json = rel.endswith(".json")
                dump = json.dumps if is_json else dump_yaml_str
                parse = json.loads if is_json else load_yaml_str
                target = self._write(script_name, rel, dump(current).encode())
                path = self._input({f"scripts/{script_name}/{rel}": dump(old).encode()})
                backup.restore_backup(path)
                restored = parse(target.read_text(encoding="utf-8"))
                self.assertEqual(restored["task"], 1)
                for key in keys:
                    restored = restored[key]
                self.assertEqual(restored, "this-machine")

    def test_empty_or_missing_current_path_is_not_imported(self):
        script, rel = "BetterGI", "User/config.json"
        self.roots[script] = str(self.root / script)
        payload = b'{"genshinStartConfig":{"installPath":"old"},"task":1}'
        for current in (
            None,
            {},
            {"genshinStartConfig": {}},
            {"genshinStartConfig": {"installPath": ""}},
        ):
            with self.subTest(current=current):
                target = Path(self.roots[script], rel)
                if current is None:
                    target.unlink(missing_ok=True)
                else:
                    self._write(script, rel, json.dumps(current).encode())
                backup.restore_backup(self._input({f"scripts/{script}/{rel}": payload}))
                restored = json.loads(target.read_bytes())
                node = restored["genshinStartConfig"]
                if current == {"genshinStartConfig": {"installPath": ""}}:
                    self.assertEqual(node["installPath"], "")
                else:
                    self.assertNotIn("installPath", node)
                self.assertEqual(restored["task"], 1)

    def test_missing_backup_path_is_filled_from_current_and_bom_preserved(self):
        script, rel = "BetterGI", "User/config.json"
        self.roots[script] = str(self.root / script)
        target = self._write(
            script, rel, b'\xef\xbb\xbf{"genshinStartConfig":{"installPath":"current"}}'
        )
        backup.restore_backup(
            self._input({f"scripts/{script}/{rel}": b'\xef\xbb\xbf{"task":1}'})
        )
        self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(
            json.loads(target.read_bytes()),
            {"task": 1, "genshinStartConfig": {"installPath": "current"}},
        )

    def test_invalid_path_config_does_not_overwrite_current_file(self):
        for script, rel in (
            ("BetterGI", "User/config.json"),
            ("March7th-Launcher", "config.yaml"),
        ):
            self.roots[script] = str(self.root / script)
            for current, incoming in ((b"broken [", b"{}"), (b"{}", b"broken [")):
                with self.subTest(script=script, current=current):
                    target = self._write(script, rel, current)
                    with self.assertRaisesRegex(OSError, "已恢复 0 个文件.*未回滚"):
                        backup.restore_backup(
                            self._input({f"scripts/{script}/{rel}": incoming})
                        )
                    self.assertEqual(target.read_bytes(), current)
                    self.assertFalse(list(target.parent.glob(".odh-*")))

    def test_unchanged_path_file_keeps_original_bytes(self):
        script, rel = "ok-ww", "data/apps/ok-ww/working/configs/devices.json"
        self.roots[script] = str(self.root / script)
        payload = b'{ "pc_full_path": "same", "task": 1 }\r\n'
        target = self._write(script, rel, b'{"pc_full_path":"same","task":99}')
        backup.restore_backup(self._input({f"scripts/{script}/{rel}": payload}))
        self.assertEqual(target.read_bytes(), payload)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.roots = {
            "first": str(self.root / "first"),
            "second": str(self.root / "second"),
        }
        self._write("first", "config/a.json", b'{"game_path": "old", "task": 1}')
        self._write("second", "config.yaml", b"task: 1\n")
        for name, kwargs in (
            (
                "iter_backup_paths",
                {
                    "return_value": {
                        "first": ("config",),
                        "second": ("config.yaml",),
                        "absent": ("config",),
                    }
                },
            ),
            ("get_script_root_dir", {"side_effect": self.roots.get}),
            ("get_path_under_root", {"side_effect": self._backup_directory}),
        ):
            patcher = patch.object(backup, name, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _backup_directory(self, *subs):
        directory = self.root.joinpath(*subs)
        directory.mkdir(parents=True, exist_ok=True)
        return str(directory)

    def _write(self, script, rel, payload):
        assert script in self.roots
        path = Path(self.roots[script], rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def _input(self, members):
        path = self.root / "input.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
            for name, payload in members.items():
                archive.writestr(name, payload)
        return str(path)

    def test_backup_is_plain_zip_without_manifest(self):
        extra = self._write("first", "config/sub/new.bin", b"\x89PNG\x00\xff")
        result = backup.create_backup()
        self.assertEqual(result["file_count"], 3)
        with zipfile.ZipFile(result["path"]) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "scripts/first/config/a.json",
                    "scripts/first/config/sub/new.bin",
                    "scripts/second/config.yaml",
                },
            )
            self.assertEqual(
                archive.read("scripts/first/config/sub/new.bin"), extra.read_bytes()
            )

    def test_repeated_backup_keeps_previous_zip(self):
        first = backup.create_backup()["path"]
        before = Path(first).read_bytes()
        second = backup.create_backup()["path"]
        self.assertNotEqual(first, second)
        self.assertEqual(Path(first).read_bytes(), before)

    def test_no_sources_reports_empty_backup(self):
        self.roots.clear()
        with self.assertRaisesRegex(ValueError, "未找到可备份"):
            backup.create_backup()

    def test_new_machine_creates_missing_files(self):
        path = backup.create_backup()["path"]
        self.roots["first"] = str(self.root / "new-machine")
        result = backup.restore_backup(path)
        self.assertEqual(result["restored"], 2)
        self.assertEqual(
            Path(self.roots["first"], "config/a.json").read_bytes(),
            b'{"game_path": "old", "task": 1}',
        )

    def test_overwrite_is_raw_and_preserves_extra_files(self):
        path = backup.create_backup()["path"]
        target = self._write(
            "first", "config/a.json", b'{"game_path": "new", "extra": true}'
        )
        extra = self._write("first", "config/new.yml", b"keep me")
        result = backup.restore_backup(path)
        self.assertEqual(target.read_bytes(), b'{"game_path": "old", "task": 1}')
        self.assertEqual(extra.read_bytes(), b"keep me")
        with zipfile.ZipFile(result["pre_backup"]) as archive:
            self.assertEqual(
                archive.read("scripts/first/config/a.json"),
                b'{"game_path": "new", "extra": true}',
            )

    def test_contents_are_not_parsed_or_limited_to_declared_filenames(self):
        payloads = {
            "scripts/first/config/broken.json": b"not JSON\x00\xff",
            "scripts/first/new-upstream-directory/config.ini": b"\xff\xfeA\x00",
            "scripts/first/config/data.bin": b"\x89PNG\r\n\x00",
            "scripts/first/config/lines.txt": b"a\r\nb\r\n",
        }
        backup.restore_backup(self._input(payloads))
        for name, payload in payloads.items():
            rel = name.split("/", 2)[2]
            self.assertEqual(Path(self.roots["first"], rel).read_bytes(), payload)

    def test_old_manifest_is_ignored_even_if_invalid(self):
        outside = self.root / "outside.txt"
        outside.write_bytes(b"untouched")
        for manifest in (
            b"invalid JSON",
            json.dumps({"version": 999, "entries": [{"src": str(outside)}]}).encode(),
        ):
            with self.subTest(manifest=manifest):
                path = self._input(
                    {
                        "manifest.json": manifest,
                        "self/config.yml": b"ignored",
                        "scripts/first/config/a.json": b"restored",
                    }
                )
                backup.restore_backup(path)
                self.assertEqual(outside.read_bytes(), b"untouched")
                self.assertEqual(
                    Path(self.roots["first"], "config/a.json").read_bytes(), b"restored"
                )

    def test_missing_scripts_are_reported_and_can_be_restored_later(self):
        path = backup.create_backup()["path"]
        second = self.roots.pop("second")
        self._write("first", "config/a.json", b"current")
        result = backup.restore_backup(path)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["restored"], 1)
        self.assertEqual(result["skipped_scripts"], ["second"])
        self.roots["second"] = second
        self._write("second", "config.yaml", b"modified")
        self.assertEqual(backup.restore_backup(path)["restored"], 2)
        self.assertEqual(Path(second, "config.yaml").read_bytes(), b"task: 1\n")

    def test_all_scripts_missing_does_not_claim_success(self):
        path = backup.create_backup()["path"]
        self.roots.clear()
        result = backup.restore_backup(path)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["restored"], 0)
        self.assertEqual(result["skipped_scripts"], ["first", "second"])
        self.assertIsNone(result["pre_backup"])

    def test_plain_zip_directory_entries_are_accepted(self):
        path = self._input(
            {
                "scripts/": b"",
                "scripts/first/": b"",
                "scripts/first/config/item": b"data",
            }
        )
        self.assertEqual(backup.restore_backup(path)["restored"], 1)

    def test_path_escape_rejected_before_any_write(self):
        target = Path(self.roots["first"], "config/a.json")
        original = target.read_bytes()
        for rel in (
            "../../outside",
            "/absolute",
            "C:/outside",
            "config/../outside",
            "config/a:ads",
            "config\\..\\..\\outside",
            "config/NUL",
            "config/a.",
            "config/a ",
        ):
            with self.subTest(rel=rel):
                path = self._input(
                    {
                        "scripts/first/config/a.json": b"changed",
                        f"scripts/first/{rel}": b"bad",
                    }
                )
                with self.assertRaises(ValueError):
                    backup.restore_backup(path)
                self.assertEqual(target.read_bytes(), original)

    def test_link_redirection_is_rejected(self):
        with (
            patch.object(
                Path, "resolve", side_effect=[self.root, self.root / "outside"]
            ),
            self.assertRaisesRegex(ValueError, "重定向"),
        ):
            backup._target_path(str(self.root), "config/file")

    def test_duplicate_targets_rejected(self):
        path = self._input({"scripts/first/config/a.json": b"a"})
        with zipfile.ZipFile(path, "a") as archive, self.assertWarns(UserWarning):
            archive.writestr("scripts/first/config/a.json", b"b")
        with self.assertRaisesRegex(ValueError, "重复目标"):
            backup.restore_backup(path)

    def test_corrupt_zip_does_not_touch_targets(self):
        target = Path(self.roots["first"], "config/a.json")
        original = target.read_bytes()
        path = self._input(
            {
                "scripts/first/config/a.json": b"changed",
                "scripts/second/config.yaml": b"unique-content",
            }
        )
        data = Path(path).read_bytes().replace(b"unique-content", b"broken-content")
        Path(path).write_bytes(data)
        with self.assertRaisesRegex(ValueError, "校验失败"):
            backup.restore_backup(path)
        self.assertEqual(target.read_bytes(), original)

    def test_unrelated_zip_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "ZIP 内没有"):
            backup.restore_backup(self._input({"photo.png": b"image"}))

    def test_backup_failure_leaves_no_incomplete_archive(self):
        with (
            patch.object(zipfile.ZipFile, "write", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            backup.create_backup()
        self.assertEqual(list((self.root / "config/backups").glob("*.zip")), [])

    def test_pre_backup_failure_does_not_write_targets(self):
        path = backup.create_backup()["path"]
        with (
            patch.object(backup, "_write_zip", side_effect=OSError("disk full")),
            patch.object(backup, "_copy_member") as copy,
        ):
            with self.assertRaises(OSError):
                backup.restore_backup(path)
            copy.assert_not_called()

    def test_partial_failure_reports_progress_and_preserves_failed_file(self):
        path = backup.create_backup()["path"]
        first = self._write("first", "config/a.json", b"first current")
        second = self._write("second", "config.yaml", b"second current")
        replace = os.replace

        def fail_second(source, target):
            if target == second:
                raise PermissionError("locked")
            return replace(source, target)

        with (
            patch.object(backup.os, "replace", side_effect=fail_second),
            self.assertRaisesRegex(OSError, "已恢复 1 个文件.*未回滚") as caught,
        ):
            backup.restore_backup(path)
        self.assertEqual(first.read_bytes(), b'{"game_path": "old", "task": 1}')
        self.assertEqual(second.read_bytes(), b"second current")
        self.assertFalse(list(self.root.rglob(".odh-*")))
        saved = [
            p for p in (self.root / "config/backups").glob("*.zip") if str(p) != path
        ]
        self.assertEqual(len(saved), 1)
        self.assertIn(str(saved[0]), str(caught.exception))
        with zipfile.ZipFile(saved[0]) as archive:
            self.assertEqual(
                archive.read("scripts/first/config/a.json"), b"first current"
            )

    def test_directory_read_error_is_reported(self):
        def fail_walk(_path, onerror):
            onerror(PermissionError("unreadable"))
            return iter(())

        with (
            patch.object(backup.os, "walk", side_effect=fail_walk),
            self.assertRaises(PermissionError),
        ):
            backup.create_backup()


if __name__ == "__main__":
    unittest.main()
