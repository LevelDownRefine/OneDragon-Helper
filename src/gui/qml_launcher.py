"""QML 启动器入口：加载 QML 主场景并桥接 Python 业务逻辑。

运行：项目根下 `python -m src.gui.qml_launcher`。
与旧 Widgets GUI（python -m src.gui.main_window）并存，迁移完成后切换入口。
"""
import os
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QFont
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
from PySide6.QtWidgets import QApplication

from src.config.set_config import ScriptConfig
from src.config.subscript import resolve_script_path
from src.gui.dialogs import confirm_config_update
from src.gui.qml_bridge import QmlBridge, ScriptIconProvider
from src.gui.theme import FONT_FAMILY


def _clear_qml_cache():
    """删除 PySide6 的 QML 编译缓存目录（%LOCALAPPDATA%/python/cache/qmlcache）。

    旧缓存会读取损坏/过时的 .qmlc 编译结果导致类型解析错乱；每次启动清理
    保证 QML 场景按当前源码重新编译。目录不存在时静默跳过。
    """
    import shutil

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if not local_appdata:
        return
    cache_dir = os.path.join(local_appdata, "python", "cache", "qmlcache")
    shutil.rmtree(cache_dir, ignore_errors=True)


def main():
    # 禁用 QML 磁盘缓存 + 清理已有缓存：旧版编译缓存会导致类型解析错乱
    # （"Type IconButton unavailable" / "Cannot assign object to list property data"
    # 等误报），且删除前不重新生成——保证每次启动都是干净编译。
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    _clear_qml_cache()
    app = QApplication([])
    # 全局默认字体（与 Widgets GUI 一致）：QML Text 默认字体中文字符 fallback
    app.setFont(QFont(FONT_FAMILY))
    # 对齐旧 GUI：config 与模板不一致时弹窗确认（CLI/测试不注入）
    ScriptConfig.confirm_before_save = confirm_config_update

    # bridge 注册为 QML 单例（不是 setContextProperty）：单例由 QML 引擎强持有，
    # 事件循环中不会被 GC——context property 传 Python 对象时，Python 局部变量
    # 存活不能保证 C++ 对象持续有效，进入事件循环后 QML 侧会读到 null。
    bridge = QmlBridge()
    provider = ScriptIconProvider(bridge.games)
    bridge.icon_provider = provider  # 供 addScript 后刷新图标缓存
    qmlRegisterSingletonInstance(QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("scripticon", provider)
    qml_path = resolve_script_path("assets/qml/main.qml")
    assert qml_path and os.path.isfile(qml_path), f"[qml_launcher] QML 缺失: {qml_path}"
    # 阶段日志：定位启动卡点（正常顺序 engine loading → loaded → running）
    print("[qml] engine loading:", qml_path, flush=True)
    engine.load(QUrl.fromLocalFile(qml_path))
    print("[qml] engine loaded, rootObjects =", len(engine.rootObjects()), flush=True)
    if not engine.rootObjects():
        sys.exit(1)
    print("[qml] entering event loop", flush=True)
    app.exec()


if __name__ == "__main__":
    main()
