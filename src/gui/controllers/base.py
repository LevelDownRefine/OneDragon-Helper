"""QmlBridge 共享基类：服务实例、跨控制器共享状态、通用信号。

各职责 mixin（GameListController / TaskCardController / BackgroundController /
LaunchController / LinkController / WindowController）均继承此类，故所有 mixin
可经 self 访问 service / _games / current_index / _ui_state 等共享状态，并复用
toastRequested / gameAdded 等信号。作为 Property notify 的信号就地定义在使用
它的 mixin（与 property 同类），避免 PySide6 跨类 notify 在深继承链下生成非法
QMetaProperty（QML 加载时 C++ 段错误）。
"""

from PySide6.QtCore import QObject, Signal

from src.gui.game_list_model import GameListModel
from src.service.chain_service import ChainService


class BridgeBase(QObject):
    # 仅「被多个 mixin 调用（emit）」的信号集中于此；作为 Property notify 的信号
    # 就地定义在使用它的 mixin（与 property 同类），避免 PySide6 跨类 notify 在深
    # 继承链下生成非法 QMetaProperty（QML 加载时 C++ 段错误）。
    toastRequested = Signal(str)  # 右下角 toast 浮层文本（所有控制器共用）
    gameAdded = Signal()

    def __init__(self):
        super().__init__()
        self.service = ChainService()
        self._games: list = []
        # QML ListView 用的 model（QAbstractListModel，重排/增删精确刷新）
        self._game_model = GameListModel()
        # 图标缓存提供器（key=script_name）；addScript 后需 rebuild，故持有引用
        self.icon_provider = None
        # 与 games 一一对应（纯内存态，默认全开）
        self._enabled: list = [True]
        # ⊞ 模式：False=浏览，True=控制
        self._control_mode = False
        self.current_index = 0
        # 任务卡状态：gui_state.json 的副本/序列/周常（按 script_name 索引）
        self._ui_state = self.service.load_ui_state()
        # 副本下拉数据缓存：dungeon_list.yml 解析较贵（磁盘读 + YAML 解析），
        # 且运行期内容不变 → 在 _reload_games 时一次性构建，避免在 QML 循环/
        # 绑定反复访问 dungeonOptions 时每次重新读盘解析（曾致下拉打开卡顿）。
        self._dungeon_map_cache: dict = {}
        self._dungeon_options_cache: dict[str, list] = {}
        # 周常开关 UI 态（纯内存，不持久化）；总开关为全局 UI 态（驱动日常行开关）
        self._weekly_toggle_state: dict[str, bool] = {}
        self._master_on = True
        # 背景字段默认（_apply_current 会在构造末尾按选中脚本刷新，此处防首帧 undefined）
        self._bg_mode = "gradient"
        self._bg_url = ""
        self._grad_color = "#3a3f52"
        self._grad_char = ""
