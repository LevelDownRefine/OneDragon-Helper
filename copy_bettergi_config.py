import os
import shutil
from pathlib import Path

import yaml

from utils import BGIConfigDIR, get_path_under_cwd


CONFIG_FILE = Path(get_path_under_cwd("01.yml"))
SOURCE_DIR = Path(BGIConfigDIR)


def find_bettergi_path(config_file: Path = CONFIG_FILE) -> Path:
    """从 01.yml 中查找 BetterGI.exe 的路径。"""
    with config_file.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    for script in config.get("script_list", []):
        script_path = script.get("script_path", "")
        if script_path and Path(script_path).name.lower() == "bettergi.exe":
            return Path(script_path)

    raise FileNotFoundError(f"未在 {config_file} 中找到 BetterGI.exe 的 script_path")


def copy_bettergi_config(source_dir: Path = SOURCE_DIR, config_file: Path = CONFIG_FILE) -> Path:
    """将项目根目录 BetterGI 文件夹中的配置复制到 BetterGI 安装目录。"""
    if not source_dir.exists():
        raise FileNotFoundError(f"源配置目录不存在: {source_dir}")

    bettergi_exe = find_bettergi_path(config_file)
    target_dir = bettergi_exe.parent

    if not target_dir.exists():
        raise FileNotFoundError(f"BetterGI 目录不存在: {target_dir}")

    for item in source_dir.iterdir():
        source_path = item
        target_path = target_dir / item.name

        if source_path.is_dir():
            shutil.copytree(source_path, target_path, dirs_exist_ok=True)
        else:
            shutil.copy2(source_path, target_path)

    return target_dir


if __name__ == "__main__":
    copied_to = copy_bettergi_config()
    print(f"BetterGI 配置已复制到: {os.fspath(copied_to)}")
