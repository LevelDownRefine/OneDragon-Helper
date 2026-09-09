"""测试配置备份（src/service/backup_service.py）。

文件系统全部落在临时目录：项目根与脚本根目录经 patch 重定向，
不触碰真实 config 与各游戏脚本 config。
"""

import json
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from src.service import backup_service

_REL_DIR = "data/apps"
"""整个目录都是 config 的目录（ok-ww 的 working/configs 同形态）。"""

_REL_OK = "data/apps/ok-ww/DailyTask.json"
_REL_DIR_OTHER = "data/apps/Other.json"
"""目录内未在声明清单里的文件：整目录备份应连它一起进包。"""

_REL_MISSING = "data/apps/ok-ww/devices.json"
_REL_SOLO = "config.yaml"
"""目录外的散装 config（崩铁同形态）。"""


class TestBackupService(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.config_dir = os.path.join(self.root, "config")
        os.makedirs(os.path.join(self.config_dir, "script_chain"))
        self._write(os.path.join(self.config_dir, "config.yml"), "script_list: []\n")
        self._write(
            os.path.join(self.config_dir, "script_chain", "today.yml"), "chain: []\n"
        )
        # 假脚本根目录：只放 _REL_OK 与 _REL_DIR_OTHER，_REL_MISSING 故意缺失
        self.script_root = os.path.join(self.root, "fake_script")
        self._write(os.path.join(self.script_root, _REL_OK), '{"task": 1}')
        self._write(os.path.join(self.script_root, _REL_DIR_OTHER), "{}")
        # 第二个脚本：只有目录外的散装 config（无 config 目录声明）
        self.solo_root = os.path.join(self.root, "solo_script")
        self._write(os.path.join(self.solo_root, _REL_SOLO), "game_path: x\n")

        self._patch("get_root_dir", return_value=self.root)
        self._patch("get_path_under_root", side_effect=self._under_root)
        self._patch(
            "iter_config_rel_paths",
            return_value={
                "ok-ww": [_REL_OK, _REL_MISSING],
                "solo": [_REL_SOLO],
                "absent": [_REL_OK],
            },
        )
        self._patch("iter_config_dir_rel_paths", return_value={"ok-ww": _REL_DIR})
        roots = {"ok-ww": self.script_root, "solo": self.solo_root}
        self._patch("get_script_root_dir", side_effect=roots.get)

    def _patch(self, name, **kwargs):
        patcher = patch.object(backup_service, name, **kwargs)
        patched = patcher.start()
        self.addCleanup(patcher.stop)
        return patched

    def _under_root(self, *subs):
        """替代 get_path_under_root：与生产一致，拼接并创建目录。"""
        path = os.path.join(self.root, *subs)
        os.makedirs(path, exist_ok=True)
        return path

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def _names(self, zip_path):
        with zipfile.ZipFile(zip_path) as archive:
            return set(archive.namelist())

    def test_create_backup_packs_self_and_script_configs(self):
        """自身 config 全目录 + 子脚本已存在的 config 进包，缺失文件跳过。"""
        path = backup_service.create_backup()

        self.assertTrue(os.path.isfile(path))
        self.assertIn("config", path)
        names = self._names(path)
        self.assertIn("manifest.json", names)
        self.assertIn("self/config.yml", names)
        self.assertIn("self/script_chain/today.yml", names)
        self.assertIn(f"scripts/ok-ww/{_REL_OK}", names)
        self.assertNotIn(f"scripts/ok-ww/{_REL_MISSING}", names)
        self.assertNotIn(f"scripts/absent/{_REL_OK}", names)

    def test_packs_whole_config_dir_without_duplicates(self):
        """整目录备份：目录内未在声明清单的文件也进包，且与声明文件不重复。"""
        self._write(os.path.join(self.script_root, "data/apps/ok-ww/Sub/a.json"), "{}")
        path = backup_service.create_backup()

        script_entries = [
            e
            for e in backup_service.read_manifest(path)["entries"]
            if e["kind"] == "script"
        ]
        rels = [entry["rel"] for entry in script_entries]
        self.assertIn(_REL_OK, rels)
        self.assertIn(_REL_DIR_OTHER, rels)  # 目录内的其他 config
        self.assertIn("data/apps/ok-ww/Sub/a.json", rels)  # 子目录
        self.assertEqual(len(rels), len(set(rels)))  # 目录与单文件重叠处已去重

    def test_packs_loose_config_outside_dir(self):
        """目录外的散装 config（如崩铁 config.yaml）按声明进包。"""
        path = backup_service.create_backup()
        self.assertIn(f"scripts/solo/{_REL_SOLO}", self._names(path))

    def test_manifest_records_kind_and_source_path(self):
        """清单按 kind 区分来源，src 为恢复用的绝对路径。"""
        path = backup_service.create_backup()
        manifest = backup_service.read_manifest(path)

        self.assertEqual(manifest["version"], backup_service.MANIFEST_VERSION)
        kinds = {entry["kind"] for entry in manifest["entries"]}
        self.assertEqual(kinds, {"self", "script"})
        script_entry = next(
            e
            for e in manifest["entries"]
            if e["kind"] == "script" and e["rel"] == _REL_OK
        )
        self.assertEqual(script_entry["script_name"], "ok-ww")
        self.assertEqual(
            script_entry["src"],
            os.path.normpath(os.path.join(self.script_root, _REL_OK)),
        )

    def test_backed_up_content_matches_source(self):
        """包内文件与源文件字节一致。"""
        path = backup_service.create_backup()
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(
                archive.read("self/config.yml").decode("utf-8"), "script_list: []\n"
            )
            self.assertEqual(
                json.loads(archive.read(f"scripts/ok-ww/{_REL_OK}")), {"task": 1}
            )

    def test_backup_excludes_own_artifacts(self):
        """备份产物目录不进包：连续两次备份，第二个包不含第一个包。"""
        first = backup_service.create_backup()
        first_name = os.path.basename(first)
        second = backup_service.create_backup()

        self.assertNotEqual(first, second)
        self.assertNotIn(f"self/backups/{first_name}", self._names(second))


if __name__ == "__main__":
    unittest.main()
