"""测试配置备份与恢复（src/service/backup_service.py）。

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
"""目录内未单列声明的文件：整目录备份应连它一起进包。"""

_REL_SOLO = "config.yaml"
"""散装单文件 config（崩铁同形态）。"""

_REL_SOLO_MISSING = "settings/missing.yml"
"""声明了但磁盘上不存在的文件：跳过，不中断整包。"""


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
        # 假脚本根目录：放 _REL_OK 与 _REL_DIR_OTHER
        self.script_root = os.path.join(self.root, "fake_script")
        self._write(os.path.join(self.script_root, _REL_OK), '{"task": 1}')
        self._write(os.path.join(self.script_root, _REL_DIR_OTHER), "{}")
        # 第二个脚本：只有散装单文件 config（崩铁同形态）
        self.solo_root = os.path.join(self.root, "solo_script")
        self._write(os.path.join(self.solo_root, _REL_SOLO), "game_path: x\n")

        self._patch("get_path_under_root", side_effect=self._under_root)
        self._patch(
            "iter_backup_paths",
            return_value={
                "ok-ww": (_REL_DIR,),
                "solo": (_REL_SOLO, _REL_SOLO_MISSING),
                "absent": (_REL_OK,),
            },
        )
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

    def test_create_backup_packs_only_script_configs(self):
        """只打包子脚本备份范围；自身 config 不进包；缺失路径与根目录不可解析的脚本跳过。"""
        path = backup_service.create_backup()

        self.assertTrue(os.path.isfile(path))
        self.assertIn("config", path)
        names = self._names(path)
        self.assertIn("manifest.json", names)
        self.assertNotIn("self/config.yml", names)  # 自身 config 不进包
        self.assertIn(f"scripts/ok-ww/{_REL_OK}", names)
        self.assertNotIn(f"scripts/solo/{_REL_SOLO_MISSING}", names)  # 文件缺失
        self.assertNotIn(f"scripts/absent/{_REL_OK}", names)  # 根目录不可解析

    def test_packs_declared_dir_recursively(self):
        """声明为目录的备份路径：整目录递归进包（含子目录）。"""
        self._write(os.path.join(self.script_root, "data/apps/ok-ww/Sub/a.json"), "{}")
        path = backup_service.create_backup()

        rels = [
            entry["rel"]
            for entry in backup_service.read_manifest(path)["entries"]
            if entry["kind"] == "script"
        ]
        self.assertIn(_REL_OK, rels)
        self.assertIn(_REL_DIR_OTHER, rels)  # 目录内的其他 config
        self.assertIn("data/apps/ok-ww/Sub/a.json", rels)  # 子目录
        self.assertEqual(len(rels), len(set(rels)))  # 每条路径只收录一次

    def test_packs_declared_loose_file(self):
        """声明为文件的备份路径（如崩铁 config.yaml）按条进包。"""
        path = backup_service.create_backup()
        self.assertIn(f"scripts/solo/{_REL_SOLO}", self._names(path))

    def test_manifest_records_kind_and_source_path(self):
        """清单按 kind 区分来源，src 为恢复用的绝对路径。"""
        path = backup_service.create_backup()
        manifest = backup_service.read_manifest(path)

        self.assertEqual(manifest["version"], backup_service.MANIFEST_VERSION)
        kinds = {entry["kind"] for entry in manifest["entries"]}
        self.assertEqual(kinds, {"script"})
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
        """包内子脚本文件与源文件字节一致。"""
        path = backup_service.create_backup()
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(
                json.loads(archive.read(f"scripts/ok-ww/{_REL_OK}")), {"task": 1}
            )

    def test_backup_excludes_own_artifacts(self):
        """备份产物不进包：连续两次备份互不包含对方产物，且自身 config 永不进包。"""
        first = backup_service.create_backup()
        first_name = os.path.basename(first)
        second = backup_service.create_backup()

        self.assertNotEqual(first, second)
        names = self._names(second)
        self.assertNotIn(first_name, names)
        self.assertFalse(any(n.startswith("self/") for n in names))

    # ── 恢复 ──────────────────────────────────────────────────
    def _declare_game_path(self):
        """声明 solo 的 config.yaml 承载游戏路径（崩铁同形态）。"""
        self._patch(
            "get_game_path_keys",
            side_effect=lambda _name, rel: ("game_path",) if rel == _REL_SOLO else None,
        )

    def _read_yaml(self, path):
        from src.utils.utils_yaml import load_yaml_str

        with open(path, encoding="utf-8") as f:
            return load_yaml_str(f.read())

    def test_restore_reverts_modified_config(self):
        """改动过的子脚本 config 恢复回备份内容。"""
        zip_path = backup_service.create_backup()
        target = os.path.join(self.script_root, _REL_OK)
        self._write(target, '{"task": 99}')

        result = backup_service.restore_backup(zip_path)

        self.assertEqual(result["status"], "ok")
        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"task": 1}')
        self.assertTrue(os.path.isfile(result["pre_backup"]))  # 恢复前自动备份

    def test_restore_keeps_existing_game_path(self):
        """目标已设置游戏路径 → 保留现值，其余字段仍用备份值覆盖。"""
        self._declare_game_path()
        target = os.path.join(self.solo_root, _REL_SOLO)
        self._write(target, "game_path: old\ntask: 1\n")
        zip_path = backup_service.create_backup()
        self._write(target, "game_path: new\ntask: 99\n")

        result = backup_service.restore_backup(zip_path)

        restored = self._read_yaml(target)
        self.assertEqual(restored["game_path"], "new")  # 现值保留
        self.assertEqual(restored["task"], 1)  # 其余字段来自备份
        self.assertEqual(result["game_path_kept"], 1)

    def test_restore_uses_backup_game_path_when_unset(self):
        """目标游戏路径为空 → 不保留，用备份值。"""
        self._declare_game_path()
        target = os.path.join(self.solo_root, _REL_SOLO)
        self._write(target, "game_path: old\ntask: 1\n")
        zip_path = backup_service.create_backup()
        self._write(target, "game_path: ''\ntask: 99\n")

        result = backup_service.restore_backup(zip_path)

        restored = self._read_yaml(target)
        self.assertEqual(restored["game_path"], "old")
        self.assertEqual(result["game_path_kept"], 0)

    def test_restore_skips_keep_when_backup_lacks_node(self):
        """备份时游戏路径节点尚未生成、恢复时当前已设置：不崩溃、不保留、其余字段照常恢复。

        模拟「脚本版本演进 / 旧备份」场景：当前文件有 a.b，备份只有 a.c。恢复应跳过
        保留现值（退回用备份值），而非 assert 中断整次恢复（P1 修复前会崩）。
        """
        self._patch(
            "get_game_path_keys",
            side_effect=lambda _n, rel: ("a", "b") if rel == _REL_SOLO else None,
        )
        target = os.path.join(self.solo_root, _REL_SOLO)
        # 备份时 a.b 尚未生成
        self._write(target, "a:\n  c: x\nother: 1\n")
        zip_path = backup_service.create_backup()
        # 恢复前：当前已设置 a.b=new，且 other 被改（验证仍被备份覆盖）
        self._write(target, "a:\n  b: new\n  c: x\nother: 99\n")

        result = backup_service.restore_backup(zip_path)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["game_path_kept"], 0)  # 未保留现值
        restored = self._read_yaml(target)
        self.assertEqual(restored.get("a"), {"c": "x"})  # 用备份内容（无 b 节点）
        self.assertEqual(restored["other"], 1)  # 其余字段来自备份


if __name__ == "__main__":
    unittest.main()
