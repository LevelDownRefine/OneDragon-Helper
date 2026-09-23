"""在独立进程中加载指定 Qt 图片插件；进程退出后释放 DLL。"""

import argparse
import logging
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImage

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugins", type=Path)
    parser.add_argument("samples", type=Path, nargs="+")
    args = parser.parse_args()
    app = QCoreApplication([])
    assert app is not None
    # 新进程中只搜索打包插件，防止开发插件及已加载的解码器缓存掩盖缺失。
    QCoreApplication.setLibraryPaths([str(args.plugins.resolve())])
    for sample in args.samples:
        if QImage(str(sample)).isNull():
            raise ValueError(f"打包插件无法解码图片：{sample}")
        logger.info("已解码：%s", sample)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
