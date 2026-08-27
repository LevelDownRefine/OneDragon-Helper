"""脚本列表控制器：脚本列表 / 当前选中 / 启用态 / 控制模式 / 重排 / 增删 / 配置弹窗。

独立 QObject，自管状态（_games / _enabled / _control_mode / current_index /
_game_model / icon_provider）。
"""

import os

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QPixmap
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtWidgets import QMessageBox

from src.config.set_config import set_weekly_start_day
from src.config.subscript import get_script_name
from src.gui.icons import get_script_icon

# 游戏图标停用底色（渐变兜底水印等场景复用）
C_GAME_DIM = "#161C28"


class ScriptIconProvider(QQuickImageProvider):
    """QML 脚本图标源：`image://scripticon/<script_name>`。

    cache key 用稳定标识 script_name（非行 index），重排后图标仍按身份解析。
    构造时预生成全部图标缓存，requestPixmap 仅查内存。
    """

    def __init__(self, games: list):
        super().__init__(QQuickImageProvider.Pixmap)
        self._cache: dict[str, QPixmap] = {}
        self.refresh(games)

    def _load_icon(self, script_data: dict) -> QPixmap:
        # 复用 icons.get_script_icon（exe 内嵌图标 / python 默认图标）
        icon = get_script_icon(script_data)
        return icon.pixmap(48, 48)

    def refresh(self, games: list):
        """增量更新图标缓存：仅提取新脚本图标，已有脚本复用缓存。"""
        for game in games:
            name = game["script_name"]
            if name not in self._cache:
                self._cache[name] = self._load_icon(game["script_data"])

    def requestPixmap(self, id: str, size, requestedSize):
        return self._cache.get(id, QPixmap())


class GameListModel(QAbstractListModel):
    """QML 脚本列表的 QAbstractListModel（ListView 数据源）。

    角色：displayName / char / color / scriptName；图标经
    ``image://scripticon/<scriptName>``（以 script_name 为稳定 cache key，重排不串图）。
    """

    DisplayNameRole = Qt.UserRole + 1
    CharRole = Qt.UserRole + 2
    ColorRole = Qt.UserRole + 3
    ScriptNameRole = Qt.UserRole + 4

    def __init__(self, games: list | None = None, parent=None):
        super().__init__(parent)
        self._games: list = list(games or [])

    def rowCount(self, parent=None) -> int:
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return len(self._games)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._games):
            return None
        game = self._games[index.row()]
        if role == self.DisplayNameRole:
            return game["display_name"]
        if role == self.CharRole:
            return game["char"]
        if role == self.ColorRole:
            return game["color"]
        if role == self.ScriptNameRole:
            return game["script_name"]
        if role == Qt.DisplayRole:
            return game["display_name"]
        return None

    def roleNames(self) -> dict:
        return {
            self.DisplayNameRole: b"displayName",
            self.CharRole: b"char",
            self.ColorRole: b"color",
            self.ScriptNameRole: b"scriptName",
        }

    @property
    def games(self) -> list:
        """内部条目列表（只读；与控制器 _games 保持一致）。"""
        return self._games

    def set_games(self, games: list):
        """整体重置（加载 config / 增删后重建），ListView 完全重建。"""
        self.beginResetModel()
        self._games = list(games)
        self.endResetModel()

    def move(self, src: int, dst: int):
        """重排：src 移到 dst 位置（ListView 精确刷新）。"""
        if src == dst or not (
            0 <= src < len(self._games) and 0 <= dst < len(self._games)
        ):
            return
        self.beginMoveRows(
            QModelIndex(),
            src,
            src,
            QModelIndex(),
            dst + 1 if dst > src else dst,
        )
        game = self._games.pop(src)
        self._games.insert(dst, game)
        self.endMoveRows()

    def append(self, game: dict):
        """末尾追加（添加脚本）。"""
        row = len(self._games)
        self.beginInsertRows(QModelIndex(), row, row)
        self._games.append(game)
        self.endInsertRows()

    def pop(self, index: int) -> dict:
        """移除指定项（ListView 精确刷新）。"""
        if not (0 <= index < len(self._games)):
            raise IndexError(index)
        self.beginRemoveRows(QModelIndex(), index, index)
        game = self._games.pop(index)
        self.endRemoveRows()
        return game


class GameListController(QObject):
    # 数据变化信号（供 QmlBridge 转发给 QML 绑定）
    gamesChanged = Signal()
    currentIndexChanged = Signal()
    enabledChanged = Signal()
    controlModeChanged = Signal()
    toastRequested = Signal(str)
    gameAdded = Signal()

    def __init__(self, service, toast, on_reload, parent=None):
        super().__init__(parent)
        self._service = service
        self._toast = toast
        self._on_reload = on_reload  # 增删/改配置后触发门面级重载
        self._games: list = []
        self._game_model = GameListModel()
        # 图标缓存提供器：数据来源本控制器 games，reload_games 时刷新
        self.icon_provider = ScriptIconProvider([])
        self._enabled: list = [True]
        self._control_mode = False
        self.current_index = 0

    # ── 读接口（供 QmlBridge 委托与跨控制器读取）────────────────────────
    @property
    def games(self) -> list:
        return self._games

    @property
    def current_game(self) -> dict:
        return self._games[self.current_index]

    @property
    def enabled(self) -> list:
        return self._enabled

    @property
    def control_mode(self) -> bool:
        return self._control_mode

    @property
    def game_model(self):
        return self._game_model

    # ── 加载 / 增删改 ───────────────────────────────────────────────────
    def reload_games(self):
        """从 config.yml 重建脚本列表。"""
        games = []
        for script in self._service.load_config().get("script_list", []):
            display_name = script["display_name"]
            games.append(
                {
                    "display_name": display_name,
                    "script_name": get_script_name(script),
                    "script_data": script,
                    "char": display_name[0],
                    "color": C_GAME_DIM,
                }
            )
        assert games, "[bridge] config.yml 中没有脚本"
        self._games = games
        self._game_model.set_games(games)
        self.current_index = min(self.current_index, len(games) - 1)
        # 新增脚本默认启用；已存在脚本保留原状态
        self._enabled = [
            self._enabled[i] if i < len(self._enabled) else True
            for i in range(len(games))
        ]
        # 增删脚本后补齐图标缓存
        self.icon_provider.refresh(self._games)
        self.gamesChanged.emit()

    # ── 交互 ───────────────────────────────────────────────────────────
    @Slot(int)
    def selectGame(self, index: int):
        """左侧图标点击：控制模式切换启停，浏览模式切换选中。"""
        assert 0 <= index < len(self._games), f"[bridge] index out of range: {index}"
        if self._control_mode:
            self._enabled[index] = not self._enabled[index]
            self.enabledChanged.emit()
            self._toast(
                f"{self._games[index]['display_name']}："
                f"{'启用' if self._enabled[index] else '停用'}"
            )
            return
        if index == self.current_index:
            return
        self.current_index = index
        self.currentIndexChanged.emit()

    @Slot()
    def toggleMode(self):
        """⊞ 模式切换：浏览（点图标选脚本）⇄ 控制（点图标切换启用/停用）。"""
        self._control_mode = not self._control_mode
        self.controlModeChanged.emit()
        self._toast(
            "控制模式：点击图标切换启用/停用"
            if self._control_mode
            else "浏览模式：点击图标选择脚本"
        )

    @Slot()
    def selectAll(self):
        """全选：所有脚本设为启用（纯内存态，不持久化）。"""
        self._enabled = [True] * len(self._games)
        self.enabledChanged.emit()
        self._toast("已全选（全部启用）")

    @Slot()
    def deselectAll(self):
        """清空：所有脚本设为停用（纯内存态，不持久化）。"""
        self._enabled = [False] * len(self._games)
        self.enabledChanged.emit()
        self._toast("已清空（全部停用）")

    @Slot(int, int)
    def reorderGames(self, src_index: int, dst_index: int):
        """拖拽重排：把 src 移到 dst 位置，同步 UI 与 config.yml。"""
        assert 0 <= src_index < len(self._games), (
            f"[bridge] src out of range: {src_index}"
        )
        assert 0 <= dst_index < len(self._games), (
            f"[bridge] dst out of range: {dst_index}"
        )
        cur_name = self._games[self.current_index][
            "script_name"
        ]  # 重排后按名字恢复选中
        game = self._games.pop(src_index)
        self._games.insert(dst_index, game)
        # QML ListView：用 rowsMoved 精确重排（modelReset 桥接不可靠）
        self._game_model.move(src_index, dst_index)
        enabled = self._enabled.pop(src_index)
        self._enabled.insert(dst_index, enabled)

        # 同步 config.yml 顺序（以 UI 顺序为准），持久化
        config_data = self._service.load_config()
        scripts = config_data["script_list"]
        s_idx = next(
            (
                i
                for i, s in enumerate(scripts)
                if get_script_name(s) == game["script_name"]
            ),
            None,
        )
        assert s_idx is not None, "[bridge] config 中找不到源脚本"
        script = scripts.pop(s_idx)
        scripts.insert(dst_index, script)
        self._service.save_config(config_data)

        # 恢复选中（新 index 可能已变）
        new_index = next(
            (i for i, g in enumerate(self._games) if g["script_name"] == cur_name),
            len(self._games) - 1,
        )
        self.gamesChanged.emit()
        self.enabledChanged.emit()
        if new_index != self.current_index:
            self.current_index = new_index
            self.currentIndexChanged.emit()
        self._toast("已调整脚本顺序")

    @Slot()
    def addScript(self):
        """弹出文件选择框，选完追加脚本到 config.yml 并重建列表。"""
        from PySide6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "选择脚本文件",
            "",
            "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)",
        )
        if not file_path:
            return
        file_path = os.path.normpath(file_path)
        existing = {g["script_name"] for g in self._games}
        script_data = self._service._script_service.build_script_entry(
            file_path, existing
        )
        self._service.add_script(script_data)
        self._on_reload()
        self._toast(f"已添加 {script_data['display_name']}")
        self.gameAdded.emit()

    @Slot(int)
    def deleteScript(self, index: int):
        """左侧拖拽到删除区：二次确认后按 index 删除脚本并落盘重载。"""
        assert 0 <= index < len(self._games), f"[bridge] index out of range: {index}"
        script_name = self._games[index]["script_name"]
        display = self._games[index].get("display_name", script_name)
        box = QMessageBox()
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("删除脚本")
        box.setText(f"确定删除「{display}」？此操作不可撤销。")
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() != QMessageBox.Ok:
            return
        self._on_delete_script(script_name)

    @Slot()
    def configCurrent(self):
        """打开当前脚本配置弹窗（SingleScriptConfigDialog）。

        Accepted → ChainService.update_script 落盘并重载；否则不落盘。
        """
        if not self._games:
            return
        game = self.current_game
        from PySide6.QtWidgets import QDialog

        from src.gui.dialogs import SingleScriptConfigDialog

        dialog = SingleScriptConfigDialog(
            game["script_name"],
            game["display_name"],
            game["script_data"].get("script_path", ""),
            None,
            script_service=self._service._script_service,
        )
        if dialog.exec() == QDialog.Accepted:
            assert dialog.pending_changes is not None, (
                "[bridge] 配置弹窗 accept 但 pending_changes 为空"
            )
            changes = dialog.pending_changes
            new_script_name = self._service.update_script(
                changes["old_script_name"],
                changes["new_display_name"],
                changes["config_patch"],
                changes["weekly_timeouts"],
            )
            # config.yml 已落盘新路径：此刻同步游戏侧原生 config 起始日，目录解析才正确。
            start_day = changes.get("weekly_start_day")
            if start_day is not None:
                self._sync_weekly_start_day(new_script_name, start_day)
            self._on_reload()
            self._toast(f"已保存 {changes['new_display_name']} 配置")

    def _sync_weekly_start_day(self, script_name: str, start_day: int) -> None:
        """落盘后把周几起同步到游戏原生 config。

        目录解析依赖 config.yml 已落盘的新 script_path，故必须在
        ChainService.update_script 之后调用。游戏侧同步为 best-effort：
        原生 config 目录因路径无效/未装游戏缺失时仅提示，不阻塞已完成的主保存。
        """
        try:
            set_weekly_start_day(script_name, start_day)
        except OSError as e:
            self._toast(f"周几起已保存，但未能同步到游戏配置：{e}")

    def _on_delete_script(self, script_name: str):
        """配置弹窗确认删除：落盘后重载脚本列表。"""
        self._service.remove_script(script_name)
        self._on_reload()
