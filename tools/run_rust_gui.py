"""构建并启动 Rust 任务卡原型；--demo 使用临时目录中的独立脚本配置。"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def prepare_demo(root: Path) -> None:
    """复制源码及静态声明，生成鸣潮/崩铁演示配置，不读取真实用户配置。"""
    shutil.copytree(
        PROJECT_ROOT / "src",
        root / "src",
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".log", "tests"),
    )
    config = root / "config"
    config.mkdir()
    for name in (
        "schedule.example.yml",
        "weekly.example.yml",
        "daily_task_list.yml",
        "weekly_task_list.yml",
    ):
        shutil.copyfile(PROJECT_ROOT / "config" / name, config / name)
    (config / "config.example.yml").write_text(
        "script_list:\n"
        "- display_name: 鸣潮\n  script_path: scripts/ok-ww.exe\n"
        "- display_name: 崩铁\n  script_path: scripts/March7th-Launcher.exe\n",
        encoding="utf-8",
    )
    scripts = root / "scripts"
    scripts.mkdir()
    for name in ("ok-ww.exe", "March7th-Launcher.exe"):
        (scripts / name).touch()
    native = scripts / "data/apps/ok-ww/working/configs/DailyTask.json"
    native.parent.mkdir(parents=True)
    native.write_text(
        json.dumps(
            {
                "Which to Farm": "Simulation Challenge",
                "Which Forgery Challenge to Farm": 20,
                "Which Tacet Suppression to Farm": 19,
                "Material Selection": "Shell Credit",
                "untouched": {"中文": [1, 2, 3]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (scripts / "config.yaml").write_text(
        "build_target_enable: false\npower_enable: true\n"
        "currencywars_enable: false\nuniverse_enable: false\n"
        "echo_of_war_enable: false\necho_of_war_start_day_of_week: 1\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="使用临时演示配置")
    parser.add_argument("--no-build", action="store_true", help="使用已有 release 构建")
    parser.add_argument(
        "--capture", type=Path, help="截图后退出（自动启用 capture 构建）"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    crate = PROJECT_ROOT / "rust-gui"
    if not args.no_build:
        command = [
            "cargo",
            "build",
            "--release",
            "--locked",
            "--manifest-path",
            str(crate / "Cargo.toml"),
        ]
        if args.capture:
            command.extend(["--features", "capture"])
        subprocess.run(command, check=True, cwd=PROJECT_ROOT)
    name = "onedragon-rust-gui.exe" if sys.platform == "win32" else "onedragon-rust-gui"
    binary = crate / "target/release" / name
    if not binary.is_file():
        logger.error("尚未构建 Rust 原型：%s", binary)
        return 2
    with tempfile.TemporaryDirectory(prefix="odh-rust-demo-") as temporary:
        root = Path(temporary) if args.demo else PROJECT_ROOT
        if args.demo:
            prepare_demo(root)
        command = [str(binary), "--project-root", str(root), "--python", sys.executable]
        if args.demo:
            command.append("--demo-label")
        if args.capture:
            command.extend(["--capture", str(args.capture.resolve())])
        logger.info("启动 Rust 界面，配置目录：%s", root)
        return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
