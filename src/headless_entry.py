"""独立 Python EXE 入口：JSONL/调度子命令及原助手 CLI，无 GUI 回退。"""

import os
import sys
from pathlib import Path

from src.headless import main as headless_main
from src.update.package import APP_EXE
from src.utils.utils_shutdown import RUST_CONFIRM_ENV


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if getattr(sys, "frozen", False):
        os.environ.setdefault(
            RUST_CONFIRM_ENV, str(Path(sys.executable).parent / APP_EXE)
        )
    if arguments and arguments[0] in {"call", "serve", "run", "daily", "legacy"}:
        return headless_main(arguments)
    return headless_main(["legacy", "--", *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
