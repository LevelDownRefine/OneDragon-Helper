"""CLI 与 GUI 客户端共用的隔离目录及无 Qt 子进程入口。"""

import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 先替换根目录再导入业务，避免测试写真实配置。
CHILD = """
import importlib.abc
import runpy
import sys
from unittest.mock import patch

class NoGui(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('PySide6', 'shiboken6') or fullname.startswith('src.gui'):
            raise AssertionError('CLI 加载了 GUI: ' + fullname)

sys.meta_path.insert(0, NoGui())
root = sys.argv.pop(1)
with patch('src.utils.get_root_dir', return_value=root):
    runpy.run_module('src.headless', run_name='__main__')
"""


class HeadlessFixture:
    def __init__(self, root: Path):
        self.root = root
        config_dir = root / "config"
        config_dir.mkdir()
        for name in (
            "schedule.example.yml",
            "weekly.example.yml",
            "daily_task_list.yml",
            "weekly_task_list.yml",
        ):
            shutil.copyfile(PROJECT_ROOT / "config" / name, config_dir / name)
        config_dir.joinpath("config.example.yml").write_text(
            "script_list:\n"
            "- display_name: 鸣潮\n  script_path: scripts/ok-ww.exe\n"
            "- display_name: 自定义脚本\n  script_path: scripts/custom.py\n",
            encoding="utf-8",
        )
        scripts = root / "scripts"
        scripts.mkdir()
        scripts.joinpath("ok-ww.exe").touch()
        scripts.joinpath("custom.py").touch()
        self.native = scripts / "data/apps/ok-ww/working/configs/DailyTask.json"
        self.native.parent.mkdir(parents=True)
        self.initial = {
            "Which to Farm": "Simulation Challenge",
            "Which Forgery Challenge to Farm": 20,
            "Which Tacet Suppression to Farm": 19,
            "Material Selection": "Shell Credit",
            "untouched": {"中文": [1, 2, 3]},
        }
        self.native.write_text(
            json.dumps(self.initial, ensure_ascii=False), encoding="utf-8"
        )

    def command(self, *args):
        return [sys.executable, "-c", CHILD, str(self.root), *args]
