"""构建 Windows Rust 完整发布包；编译产物和测试始终与用户安装分开。"""

import argparse
import ctypes
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python-backend"))

from src.update.package import (  # noqa: E402
    APP_EXE,
    RUNNER_EXE,
    RUST_RUNTIME,
    UPDATER_EXE,
    load_manifest,
    manifest_frontend,
)
from tools.release_package import (  # noqa: E402
    archive_package,
    prepare_package,
    test_package,
    validate_package,
)

logger = logging.getLogger(__name__)


def output_path(root: Path, destination: Path) -> Path:
    """只允许仓库 dist 内固定包名，拒绝链接越界和非干净的既有安装。"""
    root = root.resolve()
    dist = (root / "deploy/dist").resolve()
    target = destination.resolve()
    if (
        not dist.is_relative_to(root)
        or not target.is_relative_to(dist)
        or target.name != "OneDragon-Helper"
    ):
        raise ValueError("输出须为仓库 deploy/dist 内名为 OneDragon-Helper 的目录")
    if target.exists():
        validate_package(root, target)
        if manifest_frontend(load_manifest(target)) != "rust":
            raise ValueError("Rust 构建不能覆盖 Qt 发布目录")
    return target


def embed_resources(executable: Path, icon_path: Path) -> None:
    """仅给待发布副本写入原图标和管理员 manifest，不改开发 EXE。"""
    from PyInstaller.config import CONF
    from PyInstaller.utils.win32 import icon, winmanifest, winutils

    CONF["workpath"] = str(executable.parent)
    icon.CopyIcons(str(executable), [str(icon_path)])
    winmanifest.write_manifest_to_executable(
        str(executable), winmanifest.create_application_manifest(uac_admin=True)
    )
    winutils.update_exe_pe_checksum(str(executable))


def build(root: Path, destination: Path, *, tag: str = "", test: bool = False) -> Path:
    """完成编译/资源验证后替换干净旧产物，生成独立 Rust ZIP。"""
    destination = output_path(root, destination)
    if test and not ctypes.windll.shell32.IsUserAnAdmin():
        raise ValueError("EXE 集成测试需要管理员终端；Windows CI 会执行完整测试")
    dist = root / "deploy/dist"
    dist.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rust-build-", dir=dist) as temporary:
        staging = Path(temporary)
        subprocess.run(
            [
                "cargo",
                "build",
                "--release",
                "--locked",
                "--features",
                "capture",
                "--manifest-path",
                str(root / "rust-gui/Cargo.toml"),
                "--target-dir",
                str(root / "rust-gui/target"),
            ],
            cwd=root,
            check=True,
        )
        for component in ("CLI", "Runner", "Updater"):
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "PyInstaller",
                    "--noconfirm",
                    "--workpath",
                    str(root / "deploy/build/rust"),
                    "--distpath",
                    str(staging),
                    str(root / f"deploy/OneDragon-Helper-{component}.spec"),
                ],
                cwd=root / "deploy",
                check=True,
            )
        package = staging / "OneDragon-Helper"
        shutil.copy2(
            root / "rust-gui/target/release/onedragon-rust-gui.exe",
            package / APP_EXE,
        )
        for name in (RUNNER_EXE, UPDATER_EXE):
            shutil.copy2(staging / name, package / name)
        # Rust 启动时 Windows loader 尚不知道 Python 的 _internal 目录。
        shutil.copy2(package / "_internal" / RUST_RUNTIME, package / RUST_RUNTIME)
        embed_resources(package / APP_EXE, root / "assets/ds.ico")
        prepare_package(root, package, tag, frontend="rust")
        if test:
            code = test_package(root, package)
            if code:
                raise RuntimeError(f"EXE 集成测试失败：退出码 {code}")
        else:
            logger.info("已构建并校验发布文件；加 --test 在管理员终端验证真实 EXE")
        archive_package(root, package, staging / "OneDragon-Helper-Rust.zip")
        # 发布前重验旧目录；用户运行过的安装含配置/日志，不得覆盖或清理。
        output_path(root, destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        previous = staging / "previous"
        if destination.exists():
            destination.rename(previous)
        try:
            package.rename(destination)
        except OSError:
            if previous.exists():
                previous.rename(destination)
            raise
        for name in ("OneDragon-Helper-Rust.zip", "OneDragon-Helper-Rust.zip.sha256"):
            os.replace(staging / name, destination.parent / name)
    logger.info("Rust 发布包：%s", destination)
    return destination


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--output", type=Path, default=root / "deploy/dist/rust/OneDragon-Helper"
    )
    parser.add_argument("--tag", default=os.environ.get("ODH_RELEASE_TAG", ""))
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Rust 发布包须在 Windows MSVC 环境构建")
    build(root, args.output, tag=args.tag, test=args.test)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
