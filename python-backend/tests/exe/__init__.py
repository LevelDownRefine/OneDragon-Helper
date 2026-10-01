"""exe 集成测试包：真正启动打包产物验证实质行为（需 Windows 管理员态）。"""

import os
import pathlib

from src.update.package import MANIFEST, load_manifest, manifest_frontend


def project_root() -> str:
    """向上找到含 .gitmodules 的仓库根，避免本包内测试文件被移动后算错根。"""
    cur = pathlib.Path(__file__).resolve().parent
    root = next(
        (str(p) for p in cur.parents if (p / ".gitmodules").is_file()),
        None,
    )
    assert root is not None, "未找到仓库根 .gitmodules"
    return root


def package_dir() -> pathlib.Path:
    """构建流程指定临时测试副本；手动测试默认使用 dist。"""
    configured = os.environ.get("ODH_PACKAGE_DIR", "")
    if configured:
        return pathlib.Path(configured)
    return pathlib.Path(project_root()) / "deploy/dist/OneDragon-Helper"


def is_frontend_package(package: pathlib.Path, frontend: str) -> bool:
    """按发布清单选择前端专用测试；两种前端都包含 CLI。"""
    return (package / MANIFEST).is_file() and manifest_frontend(
        load_manifest(package)
    ) == frontend
