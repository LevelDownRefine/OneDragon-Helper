"""Qt 6a6ff09 的路径白名单快照，用于验证旧客户端升级兼容。"""

import re
from pathlib import PureWindowsPath

APP_EXE = "OneDragon-Helper.exe"

CLI_EXE = "OneDragon-Helper-CLI.exe"

RUST_RUNTIME = "vcruntime140.dll"

RUNNER_EXE = "OneDragon-Helper-Runner.exe"

UPDATER_EXE = "OneDragon-Helper-Updater.exe"

MANIFEST = "update-manifest.json"

VERSION_FILE = "version.json"

USER_CONFIG = {
    "config.yml",
    "schedule.yml",
    "weekly.yml",
    "notify_mail.yml",
    "wallpaper.json",
    "gui_state.json",
}


def managed_path(name: str) -> bool:
    """只允许程序文件，拒绝 Windows 路径别名和用户数据。"""
    if not isinstance(name, str) or not name:
        return False
    parts = name.split("/")
    if any(
        not part
        or part in (".", "..")
        or part.endswith((".", " "))
        or PureWindowsPath(part).is_reserved()
        or any(char in part for char in '\\:*?"<>|')
        or any(ord(char) < 32 for char in part)
        or re.search(r"\.bak\d*$", part, re.IGNORECASE)
        or part.casefold()
        in {"logs", ".log", "backups", "wallpaper_cache", "script_chain", ".update"}
        for part in parts
    ):
        return False
    if name in {
        APP_EXE,
        CLI_EXE,
        RUST_RUNTIME,
        RUNNER_EXE,
        UPDATER_EXE,
        VERSION_FILE,
        MANIFEST,
        "README.md",
    }:
        return True
    if parts[0] == "config":
        return len(parts) >= 2 and parts[1].casefold() not in USER_CONFIG
    if name.casefold() == "assets/banner.jpg":
        return False
    return name.startswith(("_internal/", "assets/", "src/gui/qml/"))
