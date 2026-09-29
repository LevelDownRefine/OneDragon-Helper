"""启动后空闲预热各脚本 config，使点选时已在缓存、零等待。

预热复用 ScriptConfig 工厂（functools.cache 单例 + __init__ 内 _init_config），
经 app_service.warm_config 单出口触发，不另写加载逻辑；事件循环协作调度
（每 tick 预热一个，coarse timer 省电），单线程避免 config 单例的线程安全问题。
functools.cache + _init_config 幂等，用户提前点选也已预热，timer 到它时早退零重复。
"""

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal

logger = logging.getLogger(__name__)


class ConfigWarmer(QObject):
    """逐脚本预热 config 的 Qt 调度器。"""

    finished = Signal()

    def __init__(
        self,
        script_names: list[str],
        warm_one: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._script_names = list(script_names)
        self._warm_one = warm_one
        self._index = 0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self._warm_next)

    def start(self, interval_ms: int = 150) -> None:
        """启动预热。无脚本时立即 finished。"""
        if not self._script_names:
            self.finished.emit()
            return
        self._timer.start(interval_ms)

    def _warm_next(self) -> None:
        if self._index >= len(self._script_names):
            self._timer.stop()
            self.finished.emit()
            return
        name = self._script_names[self._index]
        self._index += 1
        try:
            self._warm_one(name)
        except Exception:  # 预热失败不应拖垮启动
            logger.warning("config 预热失败: %s", name, exc_info=True)
        if self._index >= len(self._script_names):
            self._timer.stop()
            self.finished.emit()
