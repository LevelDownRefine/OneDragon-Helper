"""脚本列表控制器：脚本列表 / 当前选中 / 启用态 / 控制模式 / 重排 / 增删 / 配置弹窗。

共享状态（_games / _enabled / _control_mode / current_index / _game_model /
icon_provider / _dungeon_*_cache）由 BridgeBase 持有；本 mixin 负责增删改与
选中逻辑，并在 _reload_games 时构建副本下拉缓存（依赖 TaskCardController 的
_build_dungeon_options，经门面 QmlBridge 的 MRO 在运行时解析）。
"""

import os

from PySide6.QtCore import Property, QObject, Signal, Slot

from src.config.subscript import get_script_name
from src.gui.controllers.background import BackgroundController
from src.gui.theme import C_GAME_DIM


class GameListController(BackgroundController):
    # notify 信号就地定义（与 property 同类），避免 PySide6 跨类 notify 段错误
    gamesChanged = Signal()
    enabledChanged = Signal()
    controlModeChanged = Signal()

    @Property("QVariantList", notify=gamesChanged)
    def games(self) -> list:
        """全部脚本条目：{display_name, script_name, char, color}。"""
        return self._games

    @Property(QObject, notify=gamesChanged)
    def gameModel(self):
        """QML ListView 的 model（QAbstractListModel，重排/增删精确刷新）。"""
        return self._game_model

    @Property(int, notify=gamesChanged)
    def currentIndex(self) -> int:
        return self.current_index

    @Property("QVariantList", notify=enabledChanged)
    def enabledStates(self) -> list:
        """各脚本启用状态（与 games 一一对应；纯内存态，重启默认全开）。"""
        return self._enabled

    @Property(bool, notify=controlModeChanged)
    def controlMode(self) -> bool:
        return self._control_mode

    def _reload_games(self):
        """从 config.yml 重建脚本列表（对齐旧 GUI._load_games）。"""
        games = []
        for script in self.service.load_config().get("script_list", []):
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
        self._game_model.set_games(games)  # 同步 QML ListView model
        self.current_index = min(self.current_index, len(games) - 1)
        # 一次性解析 dungeon_list.yml 并构建所有脚本的副本下拉数据（运行期不变）
        self._dungeon_map_cache = self.service.dungeon_map()
        self._dungeon_options_cache = {
            g["script_name"]: self._build_dungeon_options(g["script_name"])
            for g in games
        }
        # 新增脚本默认启用；已存在脚本保留原状态（与旧 GUI 重建语义一致）
        self._enabled = [
            self._enabled[i] if i < len(self._enabled) else True
            for i in range(len(games))
        ]
        # 增删脚本后让图标缓存补齐新脚本（按 script_name，不重建旧图标）
        if self.icon_provider is not None:
            self.icon_provider.refresh(self._games)
        self.gamesChanged.emit()

    def _current_game(self) -> dict:
        return self._games[self.current_index]

    @Slot(int)
    def selectGame(self, index: int):
        """QML 点击左侧脚本图标：控制模式切换启停，浏览模式切换选中+刷新背景。"""
        assert 0 <= index < len(self._games), (
            f"[bridge] index out of range: {index}"
        )
        if self._control_mode:
            self._enabled[index] = not self._enabled[index]
            self.enabledChanged.emit()
            self.toastRequested.emit(
                f"{self._games[index]['display_name']}："
                f"{'启用' if self._enabled[index] else '停用'}"
            )
            return
        if index == self.current_index:
            return
        self.current_index = index
        self.gamesChanged.emit()  # 通知 QML 当前选中变化（左侧白圈跟随）
        self._apply_current()

    @Slot()
    def toggleMode(self):
        """⊞ 模式切换：浏览（点图标选脚本）⇄ 控制（点图标切换启用/停用）。"""
        self._control_mode = not self._control_mode
        self.controlModeChanged.emit()
        self.toastRequested.emit(
            "控制模式：点击图标切换启用/停用"
            if self._control_mode
            else "浏览模式：点击图标选择脚本"
        )

    @Slot()
    def selectAll(self):
        """全选：所有脚本设为启用（纯内存态，不持久化）。"""
        self._enabled = [True] * len(self._games)
        self.enabledChanged.emit()
        self.toastRequested.emit("已全选（全部启用）")

    @Slot()
    def deselectAll(self):
        """清空：所有脚本设为停用（纯内存态，不持久化）。"""
        self._enabled = [False] * len(self._games)
        self.enabledChanged.emit()
        self.toastRequested.emit("已清空（全部停用）")

    @Slot(int, int)
    def reorderGames(self, src_index: int, dst_index: int):
        """拖拽重排：把 src 移到 dst 位置，同步 UI 与 config.yml（对齐旧 GUI）。"""
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
        # QML ListView 精确重排。注意：只发 rowsMoved（move）——PySide6 的
        # modelReset（beginResetModel/endResetModel）桥接到 QML 不可靠，
        # reset 后 delegate 卡旧状态；rowsMoved 实测能正确驱动刷新。
        self._game_model.move(src_index, dst_index)
        enabled = self._enabled.pop(src_index)
        self._enabled.insert(dst_index, enabled)

        # 同步 config.yml 顺序（以 UI 顺序为准），持久化
        config_data = self.service.load_config()
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
        self.service.save_config(config_data)

        # 恢复选中（新 index 可能已变）
        self.current_index = next(
            (i for i, g in enumerate(self._games) if g["script_name"] == cur_name),
            len(self._games) - 1,
        )
        self.gamesChanged.emit()
        self.enabledChanged.emit()
        self._apply_current()
        self.toastRequested.emit("已调整脚本顺序")

    @Slot()
    def addScript(self):
        """弹出文件选择框，选完追加脚本到 config.yml 并重建列表（对齐旧 GUI）。"""
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
        script_data = self.service._script_service.build_script_entry(
            file_path, existing
        )
        self.service.add_script(script_data)
        self._reload_games()
        self.toastRequested.emit(f"已添加 {script_data['display_name']}")
        self.gameAdded.emit()

    @Slot()
    def configCurrent(self):
        """打开当前脚本配置弹窗（复用 SingleScriptConfigDialog，对齐旧 GUI）。

        保存成功（Accepted）→ ChainService.update_script 落盘并重载脚本列表；
        删除（close，非 Accepted）不落盘、不进保存分支。
        """
        if not self._games:
            return
        game = self._games[self.current_index]
        from PySide6.QtWidgets import QDialog

        from src.gui.dialogs import SingleScriptConfigDialog

        dialog = SingleScriptConfigDialog(
            game["script_name"],
            game["display_name"],
            game["script_data"].get("script_path", ""),
            None,
            script_service=self.service._script_service,
        )
        dialog.delete_requested.connect(self._on_delete_script)
        if dialog.exec() == QDialog.Accepted:
            assert dialog.pending_changes is not None, (
                "[bridge] 配置弹窗 accept 但 pending_changes 为空"
            )
            changes = dialog.pending_changes
            self.service.update_script(
                changes["old_script_name"],
                changes["new_display_name"],
                changes["config_patch"],
                changes["weekly_timeouts"],
            )
            self._reload_games()
            self.toastRequested.emit(f"已保存 {changes['new_display_name']} 配置")

    def _on_delete_script(self, script_name: str):
        """配置弹窗确认删除：落盘后重载脚本列表（对齐旧 GUI）。"""
        self.service.remove_script(script_name)
        self._reload_games()
