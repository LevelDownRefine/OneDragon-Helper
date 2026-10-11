"""助手的发布布局与受保护文件；通用更新内核不持有这些规则。"""

from updater.package import MANIFEST, VERSION_FILE
from updater.policy import UpdatePolicy

APP_EXE = "OneDragon-Helper.exe"
CLI_EXE = "OneDragon-Helper-CLI.exe"
QT_CLI_EXE = "_internal/cli/" + CLI_EXE
RUST_RUNTIME = "vcruntime140.dll"
RUNNER_EXE = "OneDragon-Helper-Runner.exe"
UPDATER_EXE = "OneDragon-Helper-Updater.exe"
REQUIRED_FILES = {
    APP_EXE,
    RUNNER_EXE,
    UPDATER_EXE,
    VERSION_FILE,
    "config/config.example.yml",
    "config/schedule.example.yml",
    "config/weekly.example.yml",
    "src/gui/qml/main.qml",
}
RUST_REQUIRED_FILES = (REQUIRED_FILES - {"src/gui/qml/main.qml"}) | {
    CLI_EXE,
    RUST_RUNTIME,
}
USER_CONFIG = {
    "config.yml",
    "schedule.yml",
    "weekly.yml",
    "notify_mail.yml",
    "wallpaper.json",
    "gui_state.json",
}


def program_path(name: str) -> bool:
    parts = name.split("/")
    if any(
        part.casefold()
        in {"logs", ".log", "backups", "wallpaper_cache", "script_chain"}
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


POLICY = UpdatePolicy(
    repository="LevelDownRefine/OneDragon-Helper",
    archive_prefix="OneDragon-Helper/",
    archives={"qt": "OneDragon-Helper.zip", "rust": "OneDragon-Helper-Rust.zip"},
    required_files={
        "qt": frozenset(REQUIRED_FILES),
        "rust": frozenset(RUST_REQUIRED_FILES),
    },
    default_frontend="qt",
    required_prefixes=("_internal/",),
    program_path=program_path,
    app_exe=APP_EXE,
    updater_exe=UPDATER_EXE,
    process_exes=(APP_EXE, CLI_EXE, QT_CLI_EXE, RUNNER_EXE),
    cli_exes={"qt": (CLI_EXE, QT_CLI_EXE), "rust": (CLI_EXE,)},
    parent_required=frozenset({"rust"}),
    restart_args=("--after-update",),
)
