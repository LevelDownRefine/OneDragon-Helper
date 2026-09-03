"""exe 集成测试包：真正启动打包产物验证实质行为（需 Windows 管理员态）。"""

import pathlib


def project_root() -> str:
    """向上找到含 pyproject.toml 的仓库根，避免本包内测试文件被移动后算错根。"""
    cur = pathlib.Path(__file__).resolve().parent
    root = next(
        (str(p) for p in cur.parents if (p / "pyproject.toml").is_file()),
        None,
    )
    assert root is not None, "未找到仓库根 pyproject.toml"
    return root
