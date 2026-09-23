"""冻结程序先取得运行锁，再导入 Qt 和业务模块。"""

import logging
import sys
from pathlib import Path

from src.service.update_package import UpdateError
from src.service.update_runtime import application_lease

logger = logging.getLogger(__name__)


def main():
    root = Path(sys.executable).parent
    try:
        with application_lease(root):
            from src.launcher import main as launch

            launch()
    except (OSError, UpdateError) as exc:
        # windowed exe 无 stderr；尽量把拒绝启动的原因留在更新日志。
        logging.basicConfig(
            filename=root / ".update" / "update.log",
            level=logging.INFO,
            encoding="utf-8",
        )
        logger.error("启动已取消: %s: %s", type(exc).__name__, exc)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
