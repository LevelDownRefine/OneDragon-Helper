"""脚本列表控制器：脚本列表 / 当前选中 / 启用态 / 控制模式 / 重排 / 增删 / 配置弹窗。

独立 QObject，自管状态（_games / _enabled / _control_mode / current_index /
_game_model / icon_provider）。
"""

import logging
import os

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QPixmap
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtWidgets import QMessageBox
from ruamel.yaml.error import YAMLError

from src.gui.icons import get_script_icon
from src.utils.utils_config import script_enabled
from src.utils.utils_sub_config import get_script_name

# 游戏图标停用底色（渐变兜底水印等场景复用）
C_GAME_DIM = "#161C28"

logger = logging.getLogger(__name__)


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
        """全量重算脚本图标到缓存。

        脚本路径变更、exe 后续就位于同一路径等场景都需即时刷新图标；
        脚本数量有限（reload 时调用一次），全量重算成本可忽略。exe 图标
        取结果由 icons._exe_icon 缓存（仅成功结果，缺失不缓存）。
        """
        # 清空后全量重算：移除已删除脚本的残留 key，避免陈旧图标滞留进程。
        self._cache = {}
        for game in games:
            name = game["script_name"]
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
    gameAdded = Signal()

    def __init__(self, app_service, toast, on_reload, parent=None):
        super().__init__(parent)
        self._app_service = app_service
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
    def current_game(self) -> dict | None:
        """当前选中脚本；config 删空（无脚本）时 None，调用方据此降级而非崩溃。"""
        if self._games:
            return self._games[self.current_index]
        return None

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
        for script in self._app_service.load_config()["script_list"]:
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
        if not games:
            # 手改 config.yml 删空脚本属可恢复的外部输入：降级为空界面而非崩溃
            # （删最后一个脚本已由 deleteScript 拦截，正常操作不会走到这里）。
            logger.warning("[bridge] config.yml 中没有脚本")
        self._games = games
        # 图标缓存必须先于模型重置刷新：set_games 触发 ListView 重建 delegate，
        # 重建即向提供器请求 pixmap；若刷新在其后，首帧取到空/陈旧缓存（新脚本
        # 首次即空白），刷新后不会自动重取，须重启进程才修正。
        self.icon_provider.refresh(self._games)
        self._game_model.set_games(games)
        new_index = min(self.current_index, max(len(games) - 1, 0))
        if new_index != self.current_index:
            self.current_index = new_index
            self.currentIndexChanged.emit()
        self._enabled = [script_enabled(game["script_data"]) for game in games]
        self.gamesChanged.emit()
        self.enabledChanged.emit()

    def _save_enabled(self, states: list[bool]) -> bool:
        """先经 service 保存，再更新界面；写入失败保留原勾选。"""
        changes = {
            game["script_name"]: enabled
            for game, enabled in zip(self._games, states, strict=True)
        }
        try:
            self._app_service.set_script_enabled(changes)
        except (OSError, ValueError, YAMLError) as exc:
            logger.error("保存脚本勾选失败：%s: %s", type(exc).__name__, exc)
            self._toast(f"保存脚本勾选失败：{exc}")
            return False
        self._enabled = states
        self.enabledChanged.emit()
        return True

    # ── 交互 ───────────────────────────────────────────────────────────
    @Slot(int)
    def selectGame(self, index: int):
        """左侧图标点击：控制模式切换启停，浏览模式切换选中。"""
        assert 0 <= index < len(self._games), f"[bridge] index out of range: {index}"
        if self._control_mode:
            states = self._enabled.copy()
            states[index] = not states[index]
            if not self._save_enabled(states):
                return
            self._toast(
                f"{self._games[index]['display_name']}："
                f"{'已加入手动运行' if self._enabled[index] else '已移出手动运行'}"
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
            "手动选择：点击图标选择脚本，不影响每日计划"
            if self._control_mode
            else "浏览模式：点击图标选择脚本"
        )

    @Slot()
    def selectAll(self):
        """全选并保存手动运行选择。"""
        if self._save_enabled([True] * len(self._games)):
            self._toast("手动运行已全选")

    @Slot()
    def deselectAll(self):
        """清空并保存手动运行选择，不改变每日计划。"""
        if self._save_enabled([False] * len(self._games)):
            self._toast("手动运行已清空")

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
        config_data = self._app_service.load_config()
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
        self._app_service.save_config(config_data)

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
        from src.gui.dialogs import SCRIPT_FILE_FILTER, pick_file

        file_path = pick_file(None, "选择脚本文件", SCRIPT_FILE_FILTER)
        if not file_path:
            return
        _, message = self._add_script_path(file_path)
        self._toast(message)

    def _script_drop_paths(self, urls: list) -> list[str]:
        """筛选本地脚本文件；快捷方式的启动信息由 service 解析。"""
        paths = []
        for value in urls:
            url = QUrl(value)
            path = url.toLocalFile()
            if not url.isLocalFile() or not os.path.isfile(path):
                return []
            if not path.lower().endswith((".exe", ".bat", ".py", ".lnk")):
                return []
            paths.append(path)
        return paths

    @Slot("QVariantList", result=bool)
    def canDropScripts(self, urls: list) -> bool:
        return bool(self._script_drop_paths(urls))

    @Slot("QVariantList", result=bool)
    def dropScripts(self, urls: list) -> bool:
        """外部文件拖到窗口：复用添加流程，仅记录路径，不移动或运行文件。"""
        paths = self._script_drop_paths(urls)
        if not paths:
            logger.warning("[file_drop] 拖入文件无有效脚本路径：%s", urls)
            self._toast("请拖入 .exe、.bat、.py 文件或指向这些文件的有效快捷方式")
            return False
        logger.info("[file_drop] 添加脚本：%s", paths)
        results = [self._add_script_path(path) for path in paths]
        added = sum(status == "added" for status, _ in results)
        logger.info("[file_drop] 已添加 %d / %d 个脚本", added, len(paths))
        if len(results) == 1:
            self._toast(results[0][1])
        else:
            duplicate = sum(status == "duplicate" for status, _ in results)
            failed = sum(status == "failed" for status, _ in results)
            summary = f"已添加 {added} 个脚本"
            if duplicate:
                summary += f"，重复 {duplicate} 个"
            if failed:
                summary += f"，失败 {failed} 个"
            details = [
                f"{os.path.basename(path)}：{message}"
                for path, (status, message) in zip(paths, results, strict=True)
                if status != "added"
            ]
            self._toast("\n".join([summary, *details]))
        return added > 0

    def _add_script_path(self, file_path: str) -> tuple[str, str]:
        """添加单个脚本并返回状态与提示，调用方统一展示结果。"""
        file_path = os.path.normpath(file_path)
        existing = {g["script_name"] for g in self._games}
        try:
            script_data = self._app_service.build_script_entry(file_path, existing)
        except (OSError, ValueError) as exc:
            logger.warning("读取脚本未完成：%s", file_path, exc_info=True)
            return "failed", f"无法添加 {os.path.basename(file_path)}：{exc}"
        # exe 的内部标识固定为进程名，改展示名无法消除重复。
        if get_script_name(script_data) in existing:
            return "duplicate", f"脚本已存在：{get_script_name(script_data)}"
        try:
            self._app_service.add_script(script_data)
        except OSError as exc:
            logger.warning("添加脚本未完成：%s", file_path, exc_info=True)
            # config.yml 可能已保存，后续子配置初始化才失败，须重读实际状态。
            self._on_reload()
            return "failed", f"添加脚本未完成：{exc}"
        self._on_reload()
        assert "display_name" in script_data
        self.gameAdded.emit()
        return "added", f"已添加 {script_data['display_name']}"

    @Slot(int)
    def deleteScript(self, index: int):
        """左侧拖拽到删除区：二次确认后按 index 删除脚本并落盘重载。"""
        assert 0 <= index < len(self._games), f"[bridge] index out of range: {index}"
        if len(self._games) <= 1:
            # 删光脚本会让列表/任务卡失去当前项，属可恢复的用户操作，拦截并提示。
            self._toast("至少保留一个脚本，无法删除")
            return
        script_name = self._games[index]["script_name"]
        display = self._games[index]["display_name"]
        from src.gui.dialogs import styled_msg_box

        box = styled_msg_box(
            None,
            QMessageBox.Warning,
            "删除脚本",
            f"确定删除「{display}」？此操作不可撤销。",
        )
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() != QMessageBox.Ok:
            return
        self._on_delete_script(script_name)

    @Slot()
    def configCurrent(self):
        """打开当前脚本配置弹窗（SingleScriptConfigDialog）。

        Accepted → AppService.update_script 落盘并重载；否则不落盘。
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
            app_service=self._app_service,
        )
        if dialog.exec() == QDialog.Accepted:
            assert dialog.pending_changes is not None, (
                "[bridge] 配置弹窗 accept 但 pending_changes 为空"
            )
            changes = dialog.pending_changes
            # 周几起（weekly.yml 段 + 游戏侧同步）由 update_script 统一落盘；
            # 游戏侧 OSError 属部分失败（config.yml 已落盘），提示不回滚。
            try:
                self._app_service.update_script(
                    changes["old_script_name"],
                    changes["new_display_name"],
                    changes["config_patch"],
                    changes["weekly_timeouts"],
                    changes["weekly_start_day"],
                )
            except OSError as e:
                self._toast(f"配置已保存，但周几起未能同步到游戏配置：{e}")
            self._on_reload()
            self._toast(f"已保存 {changes['new_display_name']} 配置")

    def _on_delete_script(self, script_name: str):
        """配置弹窗确认删除：落盘后重载脚本列表。"""
        self._app_service.remove_script(script_name)
        self._on_reload()
