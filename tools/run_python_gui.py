"""从当前检出的源码启动 Python GUI，避免共享环境指向其他工作树。"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    """使用当前解释器启动检出目录中的 GUI 与后端。

    Args:
        argv: 透传给 GUI 的参数；省略时使用当前进程参数。

    Returns:
        GUI 进程的退出码。
    """
    env = os.environ.copy()
    paths = [
        str(PROJECT_ROOT / "python-gui/src"),
        str(PROJECT_ROOT / "python-backend"),
        str(PROJECT_ROOT / "python-backend/src"),
    ]
    if "PYTHONPATH" in env and env["PYTHONPATH"]:
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "gui.launcher",
            *(sys.argv[1:] if argv is None else argv),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
