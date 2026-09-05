"""启动器入口：GUI 启动 + 无头 CLI 出口。

GUI 走 QML（src/gui/main_window 桥接业务逻辑，src/gui/qml/main.qml 渲染）；
单脚本配置弹窗在 src/gui/dialogs.py。
无头 CLI 出口见 :mod:`src.cli`（本模块的 --generate-chain / --run-chain 等命令行参数）。
"""

import logging
import os
import shutil
import sys
import time

from PySide6.QtCore import QUrl
from PySide6.QtGui import QFont
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
from PySide6.QtWidgets import QApplication

from src.cli import build_parser, run_cli
from src.config.generate_config import config_workflow
from src.gui.main_window import QmlBridge
from src.utils.utils_logger import setup_logging
from src.utils.utils_sub_config import resolve_script_path

# 全局默认字体：QML Text 默认字体中文字符 fallback；与旧 GUI 一致
FONT_FAMILY = "Microsoft YaHei"

logger = logging.getLogger(__name__)

# 启动耗时打点基准（模块导入完成后、main() 入口处归零）
_STARTUP_T0 = time.perf_counter()


def _log_startup(stage: str) -> None:
    """记录启动阶段耗时：相对 main() 入口的毫秒数（供启动性能分析）。"""
    elapsed_ms = (time.perf_counter() - _STARTUP_T0) * 1000
    logger.info("[startup] %-30s %8.1f ms", stage, elapsed_ms)


def _clear_qml_cache():
    """删除 PySide6 的 QML 编译缓存目录（%LOCALAPPDATA%/python/cache/qmlcache）。

    旧缓存会读取损坏/过时的 .qmlc 编译结果导致类型解析错乱；每次启动清理
    保证 QML 场景按当前源码重新编译。目录不存在时静默跳过。
    """
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if not local_appdata:
        return
    cache_dir = os.path.join(local_appdata, "python", "cache", "qmlcache")
    shutil.rmtree(cache_dir, ignore_errors=True)


def main():
    # 首次运行时，拷贝配置模板到用户目录
    config_workflow()

    args = build_parser().parse_args()
    # 提前配置日志：CLI 出口（如 run_chain_command）也依赖 logger，
    # windowed exe 下 logs/onedragon_helper.log 是主要观测渠道。幂等，GUI 路径复用。
    setup_logging()
    # 模块导入耗时（_STARTUP_T0 之前）由 python -X importtime 观测；
    # 此处起记录 main() 内各阶段耗时。
    _log_startup("main() 初始化（config_workflow/parse_args/setup_logging）")

    # 非 GUI 的 CLI 出口：解析后即退出，不进入事件循环。
    exit_code = run_cli(args)
    if exit_code is not None:
        sys.exit(exit_code)
    _log_startup("run_cli")

    _launch_qml()


def _launch_qml():
    # 禁用 QML 磁盘缓存 + 清理已有缓存：旧版编译缓存会导致类型解析错乱
    # （"Type IconButton unavailable" / "Cannot assign object to list property data"
    # 等误报），且删除前不重新生成——保证每次启动都是干净编译。
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    _clear_qml_cache()

    app = QApplication(sys.argv)
    # 全局默认字体：QML Text 默认字体中文字符 fallback；与旧 GUI 一致
    app.setFont(QFont(FONT_FAMILY))

    # bridge 注册为 QML 单例（不是 setContextProperty）：单例由 QML 引擎强持有，
    # 事件循环中不会被 GC——context property 传 Python 对象时，QML 侧会读到 null。
    bridge = QmlBridge()
    qmlRegisterSingletonInstance(QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)

    engine = QQmlApplicationEngine()
    # 脚本图标源：数据归属 game_list，直接取其实例持有的 provider；
    # 通用 UI 矢量图标源由组合根 QmlBridge 暴露。
    engine.addImageProvider("scripticon", bridge.game_list.icon_provider)
    engine.addImageProvider("uiicon", bridge.ui_icon_provider)
    qml_path = resolve_script_path("src/gui/qml/main.qml")
    assert qml_path and os.path.isfile(qml_path), f"[launcher] QML 缺失: {qml_path}"
    # 阶段日志：定位启动卡点（正常顺序 engine loading → loaded → running）
    print("[qml] engine loading:", qml_path, flush=True)
    engine.load(QUrl.fromLocalFile(qml_path))
    print("[qml] engine loaded, rootObjects =", len(engine.rootObjects()), flush=True)
    if not engine.rootObjects():
        sys.exit(1)
    # GUI 打开即弹 60s 倒计时确认：取消则无事发生，归零/「立即启动」按上次配置启动全部。
    # 须在进入事件循环前同步弹模态窗（QDialog.exec 自带局部事件循环）。
    bridge.maybe_auto_launch()
    print("[qml] entering event loop", flush=True)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
