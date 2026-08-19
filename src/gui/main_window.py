"""QML GUI 中央控制器（单例）：组合各职责 mixin，编排启动初始化。

QML 经 qmlRegisterSingletonInstance 注册为 `Bridge`，经 `Bridge.*` 访问（绝不用
setContextProperty，否则事件循环中 Python 对象被 GC 致 QML 读到 null）。

各职责拆到 src/gui/controllers/ 下独立 mixin（background / game_list /
task_card / launch / links / window），本文件只持有 QmlBridge 门面与 __init__
编排：重建脚本列表 → 还原周常开关 → 刷新背景。共享状态与信号集中在
controllers/base.BridgeBase。
"""


# 重导出：launcher 与测试经本模块便捷导入门面与依赖
from src.gui.controllers.base import ChainService
from src.gui.controllers.window import WindowController
from src.gui.providers import ScriptIconProvider, UiIconProvider


class QmlBridge(WindowController):
    """QML 应用与 Python 业务逻辑的桥接对象（context property: `Bridge`）。

    线性继承（WindowController → LinkController → … → BackgroundController →
    BridgeBase(QObject)），单 QObject 根，避免菱形多继承致 PySide6 只注册首条
    QObject 链上的信号/槽/属性、或构建非法 metaobject（QML 加载崩溃）。
    """

    def __init__(self):
        super().__init__()
        self._reload_games()
        # 启动时按 weekly_start 还原各游戏周常开关（对齐旧 GUI._init_weekly_toggle_states）；
        # 此前漏迁移，周常行始终显示关闭。需放在 _reload_games 之后（依赖 self._games）。
        self._weekly_toggle_state = self._init_weekly_toggle_states()
        self._apply_current()


__all__ = ["QmlBridge", "ChainService", "ScriptIconProvider", "UiIconProvider"]
