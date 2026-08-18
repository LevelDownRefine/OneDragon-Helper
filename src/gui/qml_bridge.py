"""QML 应用桥接：把 Python 业务逻辑（ChainService / set_config）暴露给 QML。

QML 侧通过 context property `bridge` 访问脚本列表与背景状态；脚本图标经
`image://scripticon/<index>` 由 ScriptIconProvider 提供（复用 get_script_icon，
避免 QML 直接读 exe 图标）。旧 Widgets GUI（main_window.py）保留不动，
直到 QML 迁移全部就绪再切换入口。
"""
import os
import subprocess
import sys
import webbrowser

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtQuick import QQuickImageProvider

from src.config.dungeon_config import get_display_name, parse_dungeon_config
from src.config.set_config import get_game_bg_img as _get_game_bg_img
from src.config.set_config import get_game_bilibili as _get_game_bilibili
from src.config.set_config import get_game_exe_path as _get_game_exe_path
from src.config.set_config import get_game_github as _get_game_github
from src.config.set_config import get_game_homepage as _get_game_homepage
from src.config.set_config import is_adapted
from src.config.set_config import supports_weekly as _supports_weekly
from src.config.subscript import get_script_name, resolve_script_path
from src.gui.game_list_model import GameListModel
from src.gui.theme import (
    _URL_BILIBILI,
    _URL_HOME,
    C_GAME_DIM,
    DEFAULT_BG,
    WEEKDAY_NAMES,
)
from src.gui.video_backdrop import is_video
from src.service.chain_service import ChainService
from src.utils_runner import build_script_command
from src.utils_weekly import is_weekly_start_reached


class ScriptIconProvider(QQuickImageProvider):
    """QML Image 的脚本图标源：`image://scripticon/<script_name>`。

    cache key 用 script_name 这个**稳定标识**而非行 index：重排只改行位置、
    index 不变，若按 index 缓存每格图标会停在启动时的旧图标（"图标不跟着
    重排"的根因）。按 script_name 缓存后，无论行位置怎么变，图标都按游戏身份
    正确解析。

    构造时在主线程预生成全部图标缓存（Shell 提取 exe 图标较慢，集中到
    启动阶段一次性完成），requestPixmap 只查内存缓存——避免 QML 场景
    加载期间逐图标同步提取导致窗口卡住。
    """

    def __init__(self, games: list):
        super().__init__(QQuickImageProvider.Pixmap)
        self._cache: dict[str, QPixmap] = {}
        self.refresh(games)

    def _load_icon(self, script_data: dict) -> QPixmap:
        # 复用 icons.get_script_icon（exe 内嵌图标 / python 默认图标）
        from src.gui.icons import get_script_icon

        icon = get_script_icon(script_data)
        return icon.pixmap(48, 48)

    def refresh(self, games: list):
        """增量更新缓存：只为新脚本提取图标，已有脚本复用缓存（避免重复 Shell 提取）。

        增删脚本后（_reload_games）调用，保证新脚本也能取到图标。
        """
        for game in games:
            name = game["script_name"]
            if name not in self._cache:
                self._cache[name] = self._load_icon(game["script_data"])

    def requestPixmap(self, id: str, size, requestedSize):
        return self._cache.get(id, QPixmap())


class QmlBridge(QObject):
    """QML 应用与 Python 业务逻辑的桥接对象（context property: `bridge`）。"""

    backgroundChanged = Signal()  # 背景模式/URL/渐变变化
    gamesChanged = Signal()  # 脚本列表变化（增删/重排/保存配置）
    enabledChanged = Signal()  # enabled 内存态变化（纯 UI，不持久化）
    controlModeChanged = Signal()  # ⊞ 控制模式切换
    toastRequested = Signal(str)  # 右下角 toast 浮层文本
    gameAdded = Signal()  # 添加脚本成功（QML 用于滚动列表到底部）
    taskStateChanged = Signal()  # 任务卡（日常/周常）状态变化

    def __init__(self):
        super().__init__()
        self.service = ChainService()
        self._games: list = []
        # 图标缓存提供器（key=script_name）；addScript 后需 rebuild，故持有引用
        self.icon_provider = None
        # QML ListView 用的 model（QAbstractListModel，重排/增删精确刷新）
        self._game_model = GameListModel()
        self._enabled: list = [True]  # 与 games 一一对应（纯内存态，默认全开）
        self._control_mode = False  # ⊞ 模式：False=浏览，True=控制
        self.current_index = 0
        self._bg_mode = "gradient"  # video | image | gradient
        self._bg_url = ""
        self._grad_color = C_GAME_DIM
        self._grad_char = ""
        # 任务卡状态：gui_state.json 的副本/序列/周常（按 script_name 索引）
        self._ui_state = self.service.load_ui_state()
        # 周常开关 UI 态（纯内存，不持久化）；总开关为全局 UI 态（驱动日常行开关）
        self._weekly_toggle_state: dict[str, bool] = {}
        self._master_on = True
        self._reload_games()
        self._apply_current()

    # ── 脚本列表 ─────────────────────────────────────────────────────────
    @Property("QVariantList", notify=gamesChanged)
    def games(self) -> list:
        """全部脚本条目：{display_name, script_name, char, color}。"""
        return self._games

    @Property(QObject, notify=gamesChanged)
    def gameModel(self):
        """QML ListView 的 model（QAbstractListModel，重排/增删精确刷新）。"""
        return self._game_model

    @Property(int, notify=backgroundChanged)
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
        """从 config.yml 重建脚本列表（对齐 main_window._load_games）。"""
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
        assert games, "[qml_bridge] config.yml 中没有脚本"
        self._games = games
        self._game_model.set_games(games)  # 同步 QML ListView model
        self.current_index = min(self.current_index, len(games) - 1)
        # 新增脚本默认启用；已存在脚本保留原状态（与旧 GUI 重建语义一致）
        self._enabled = [
            self._enabled[i] if i < len(self._enabled) else True
            for i in range(len(games))
        ]
        # 增删脚本后让图标缓存补齐新脚本（按 script_name，不重建旧图标）
        if self.icon_provider is not None:
            self.icon_provider.refresh(self._games)
        self.gamesChanged.emit()

    @Slot(int)
    def selectGame(self, index: int):
        """QML 点击左侧脚本图标：控制模式切换启停，浏览模式切换选中+刷新背景。"""
        assert 0 <= index < len(self._games), f"[qml_bridge] index out of range: {index}"
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
        self._apply_current()

    @Slot()
    def toggleMode(self):
        """⊞ 模式切换：浏览（点图标选脚本）⇄ 控制（点图标切换启用/停用）。"""
        self._control_mode = not self._control_mode
        self.controlModeChanged.emit()
        self.toastRequested.emit(
            "控制模式：点击图标切换启用/停用" if self._control_mode else "浏览模式：点击图标选择脚本"
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
        assert 0 <= src_index < len(self._games), f"[qml_bridge] src out of range: {src_index}"
        assert 0 <= dst_index < len(self._games), f"[qml_bridge] dst out of range: {dst_index}"
        cur_name = self._games[self.current_index]["script_name"]  # 重排后按名字恢复选中
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
            (i for i, s in enumerate(scripts) if get_script_name(s) == game["script_name"]),
            None,
        )
        assert s_idx is not None, "[qml_bridge] config 中找不到源脚本"
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
        script_data = self.service._script_service.build_script_entry(file_path, existing)
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
                "[qml_bridge] 配置弹窗 accept 但 pending_changes 为空"
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

    # ── 任务卡（日常 / 周常）──────────────────────────────────────────────
    @Property(str, notify=taskStateChanged)
    def taskTitle(self) -> str:
        """当前游戏显示名（任务卡标题）。"""
        return self._games[self.current_index]["display_name"]

    @Property(bool, notify=taskStateChanged)
    def taskAdapted(self) -> bool:
        """当前游戏是否已注册副本适配（决定日常/周常行显隐）。"""
        return is_adapted(self._games[self.current_index]["script_name"])

    @Property(bool, notify=taskStateChanged)
    def dailySupported(self) -> bool:
        """当前游戏是否有可配置日常副本（dungeon_map 有配置 → 显示日常行）。

        区别于 taskAdapted（是否在 _CONFIGS 注册）：部分游戏虽已注册，但
        dungeon_list 无实际副本（如原神仅检查、终末地骨架），无需日常行。
        """
        return bool(self.service.dungeon_map().get(self._games[self.current_index]["script_name"]))

    @Property(str, notify=taskStateChanged)
    def dailyDungeonText(self) -> str:
        """日常副本 chip 文字（持久化于 gui_state.json）。"""
        game = self._games[self.current_index]
        saved = self._ui_state.get(game["script_name"], {})
        if not saved.get("dungeon"):
            return "选择副本"
        dungeon_cfg = self.service.dungeon_map().get(game["script_name"])
        return self._dungeon_chip_text(
            dungeon_cfg, saved.get("dungeon"), saved.get("sequence")
        )

    @Property(bool, notify=taskStateChanged)
    def weeklySupported(self) -> bool:
        """当前游戏是否支持周常（决定周常行可选性 / 整行样式）。"""
        return _supports_weekly(self._games[self.current_index]["script_name"])

    @Property(str, notify=taskStateChanged)
    def weeklyStartLabel(self) -> str:
        """周常 chip 文字（周几起 / 选择周几）。"""
        game = self._games[self.current_index]
        saved = self._ui_state.get(game["script_name"], {})
        start_day = saved.get("weekly_start")
        return "选择周几" if start_day is None else f"{WEEKDAY_NAMES[start_day]}起"

    @Property(bool, notify=taskStateChanged)
    def masterOn(self) -> bool:
        """总开关状态（全局 UI 态；驱动日常行开关）。"""
        return self._master_on

    @Property(bool, notify=taskStateChanged)
    def dailyOn(self) -> bool:
        """日常行开关（镜像总开关，由 toggleMaster 驱动）。"""
        return self._master_on

    @Property(bool, notify=taskStateChanged)
    def weeklyOn(self) -> bool:
        """周常行开关（内存态，由 toggleMaster / selectWeekly 置位）。"""
        return self._weekly_toggle_state.get(
            self._games[self.current_index]["script_name"], False
        )

    @Property("QVariantList", notify=taskStateChanged)
    def dungeonOptions(self) -> list:
        """日常副本下拉数据：[{name, clear, sequences:[{label,value}]}, ...]。"""
        return self._build_dungeon_options(self._games[self.current_index]["script_name"])

    def _refresh_task_card(self):
        """切换游戏后刷新任务卡（标题/适配态/日常/周常由 Property getter 实时读取）。

        仅发信号触发 QML 重读；无需缓存字段。
        """
        self.taskStateChanged.emit()

    def _dungeon_chip_text(self, dungeon_cfg, dungeon_name: str, sequence) -> str:
        """副本 chip 文字：有二级序列且选了二级 → 二级展示名；否则副本名本身。"""
        if dungeon_name is None:
            return "选择副本"
        if dungeon_cfg:
            _, seq_map, _ = parse_dungeon_config(dungeon_cfg)
            if sequence is not None and dungeon_name in seq_map:
                return get_display_name(seq_map, dungeon_name, sequence)
        return dungeon_name

    def _build_dungeon_options(self, script_name: str) -> list:
        """构建日常副本下拉数据（一级副本 → 二级序列）。"""
        dungeon_cfg = self.service.dungeon_map().get(script_name)
        if not dungeon_cfg:
            return []
        options, seq_map, _ = parse_dungeon_config(dungeon_cfg)
        result = []
        for name in options:
            if name == "未选择":
                result.append({"name": "未选择", "clear": True, "sequences": []})
            else:
                seqs = seq_map.get(name, [])
                result.append(
                    {
                        "name": name,
                        "clear": False,
                        "sequences": [{"label": lbl, "value": val} for lbl, val in seqs],
                    }
                )
        return result

    @Slot(bool)
    def toggleMaster(self, on: bool):
        """总开关：一键同步日常/周本（支持周常时周常开关一并置位）。"""
        self._master_on = on
        script_name = self._games[self.current_index]["script_name"]
        if _supports_weekly(script_name):
            self._weekly_toggle_state[script_name] = on
        self.taskStateChanged.emit()

    @Slot(bool)
    def toggleWeekly(self, on: bool):
        """周常开关（内存态，不持久化；与日常开关模型一致）。"""
        script_name = self._games[self.current_index]["script_name"]
        self._weekly_toggle_state[script_name] = on
        self.taskStateChanged.emit()

    @Slot(str, "QVariant")
    def selectDungeon(self, dungeon_name: str, sequence):
        """选择日常副本（持久化到 gui_state.json 的 dungeon/sequence）。"""
        script_name = self._games[self.current_index]["script_name"]
        saved = self._ui_state.setdefault(script_name, {})
        if not dungeon_name or dungeon_name == "未选择":
            saved.pop("dungeon", None)
            saved.pop("sequence", None)
        else:
            saved["dungeon"] = dungeon_name
            saved["sequence"] = sequence
        self.service.save_ui_state(self._ui_state)
        self._refresh_task_card()

    @Slot(int)
    def selectWeekly(self, start_day: int):
        """选择周常起始日（持久化 weekly_start；周常开关按「今天>=起始日」置位）。"""
        assert start_day in WEEKDAY_NAMES, f"[qml_bridge] 非法周几: {start_day}"
        script_name = self._games[self.current_index]["script_name"]
        saved = self._ui_state.setdefault(script_name, {})
        saved["weekly_start"] = start_day
        enabled = is_weekly_start_reached(start_day)
        self._weekly_toggle_state[script_name] = enabled
        self.service.save_ui_state(self._ui_state)
        self._refresh_task_card()

    # ── 启动 / 运行 ─────────────────────────────────────────────────────
    @Slot()
    def launchAll(self):
        """启动全部：生成仅含启用脚本的链并运行（对齐旧 GUI enabled 语义）。"""
        keys = {
            g["script_name"]
            for g, on in zip(self._games, self._enabled, strict=True)
            if on
        }
        if not keys:
            self.toastRequested.emit("没有启用的脚本")
            return
        if not self._confirm_run(keys):
            return
        config_data = self.service.load_config()
        self._run_chain(config_data, keys, "启动全部")

    @Slot()
    def launchScript(self):
        """启动当前选中脚本（直接运行，不走链；对齐旧 GUI 图标左键语义）。"""
        game = self._games[self.current_index]
        script = game["script_data"]
        if script.get("script_type") == "python":
            resolved = resolve_script_path(script["script_path"])
            if not resolved or not os.path.isfile(resolved):
                self.toastRequested.emit(f"找不到脚本文件：{script['script_path']}")
                return
            command, cwd, env = build_script_command(["--script", resolved])
            subprocess.Popen(command, cwd=cwd, env=env)
        else:
            exe_path = script.get("script_path", "")
            resolved = resolve_script_path(exe_path) if exe_path else None
            if not resolved or not os.path.isfile(resolved):
                self.toastRequested.emit(f"找不到脚本：{exe_path}")
                return
            os.startfile(resolved)  # noqa: S606 启动脚本本体
        self.toastRequested.emit(f"已启动 {game['display_name']}")

    def _confirm_run(self, enabled_keys: set) -> bool:
        """运行前校验（对齐旧 GUI）+ 确认弹窗。True 继续，False 取消。"""
        from PySide6.QtWidgets import QMessageBox

        config_data = self.service.load_config()
        enabled_scripts = [
            s for s in config_data["script_list"] if get_script_name(s) in enabled_keys
        ]
        invalid = self.service.collect_invalid_scripts(enabled_scripts)
        if invalid:
            details = "\n".join(f"· {name}：{msg}" for name, msg in invalid)
            reply = QMessageBox.warning(
                None,
                "脚本配置不合法",
                f"以下脚本配置不合法，运行时会被跳过：\n{details}\n\n是否仍然运行？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return False
        reply = QMessageBox.question(
            None,
            "确认运行",
            f"即将运行 {len(enabled_keys)} 个脚本，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _run_chain(self, config_data: dict, enabled_keys: set, label: str) -> None:
        """生成并运行脚本链（真实 ChainService）。"""
        ui_state = {name: dict(entry) for name, entry in self._ui_state.items()}
        chain_path = self.service.generate_chain(
            config_data, enabled_keys, chain_name="today", ui_state=ui_state
        )
        command, cwd, env = build_script_command(["--chain", chain_path])
        command[0] = command[0].replace("pythonw.exe", "python.exe")
        creationflags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            creationflags=creationflags,
        )
        self.toastRequested.emit(f"{label}：已生成并运行链 ({len(enabled_keys)} 个脚本)")

    # ── 悬浮条 ─────────────────────────────────────────────────────────
    def _current_game(self) -> dict:
        return self._games[self.current_index]

    @Slot()
    def launchGame(self):
        """启动游戏：读取当前游戏 exe 路径并打开（未适配时提示）。"""
        game = self._current_game()
        exe_path = _get_game_exe_path(game["script_name"])
        if not exe_path:
            self.toastRequested.emit(f"{game['display_name']}：未找到游戏路径")
            return
        os.startfile(exe_path)  # noqa: S606 启动游戏
        self.toastRequested.emit(f"正在启动 {game['display_name']}…")

    def _open_url(self, url: str, fallback: str, label: str):
        target = url or fallback
        webbrowser.open(target)
        self.toastRequested.emit(f"打开{label}：{target}")

    @Slot()
    def openHome(self):
        """打开当前游戏官方主页（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_homepage(self._current_game()["script_name"]),
            _URL_HOME,
            "主页",
        )

    @Slot()
    def openBilibili(self):
        """打开当前游戏官方 B 站（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_bilibili(self._current_game()["script_name"]),
            _URL_BILIBILI,
            "B站",
        )

    @Slot()
    def openGithub(self):
        """打开当前脚本项目 GitHub 主页（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_github(self._current_game()["script_name"]),
            _URL_HOME,
            "GitHub",
        )

    @Slot()
    def openScriptFolder(self):
        """打开当前脚本所在目录（script_path 父目录，资源管理器）。"""
        game = self._current_game()
        script_path = game["script_data"].get("script_path", "")
        resolved = resolve_script_path(script_path) if script_path else None
        if not resolved:
            self.toastRequested.emit(f"{game['display_name']}：未找到脚本路径")
            return
        folder = os.path.dirname(resolved)
        if not os.path.isdir(folder):
            self.toastRequested.emit(f"{game['display_name']}：脚本目录不存在")
            return
        os.startfile(folder)  # noqa: S606 打开脚本所在目录
        self.toastRequested.emit(f"已打开 {game['display_name']} 脚本目录")

    @Slot()
    def openWallpaper(self):
        """更改当前脚本壁纸并持久化到 config/wallpaper.json（对齐旧 GUI）。"""
        from PySide6.QtWidgets import QFileDialog

        game = self._current_game()
        path, _ = QFileDialog.getOpenFileName(
            None,
            f"选择 {game['display_name']} 壁纸",
            "",
            "图片/视频 (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.webm *.mkv *.mov)",
        )
        if not path:
            return
        wallpapers = self._wallpapers()
        wallpapers[game["script_name"]] = path
        self._save_wallpapers(wallpapers)
        self._apply_current()
        self.toastRequested.emit(f"已更换 {game['display_name']} 壁纸")

    def _save_wallpapers(self, wallpapers: dict):
        import json

        path = resolve_script_path("config/wallpaper.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(wallpapers, f, ensure_ascii=False, indent=2)

    # ── 背景 ─────────────────────────────────────────────────────────────
    @Property(str, notify=backgroundChanged)
    def backgroundMode(self) -> str:
        return self._bg_mode

    @Property(str, notify=backgroundChanged)
    def backgroundUrl(self) -> str:
        return self._bg_url

    @Property(str, notify=backgroundChanged)
    def gradientColor(self) -> str:
        return self._grad_color

    @Property(str, notify=backgroundChanged)
    def gradientChar(self) -> str:
        return self._grad_char

    def _apply_current(self):
        """按当前选中脚本刷新背景：自定义壁纸 → 脚本背景 → 渐变兜底。"""
        game = self._games[self.current_index]
        path = self._load_bg(game)
        if path and is_video(path) and os.path.isfile(path):
            self._bg_mode = "video"
            self._bg_url = QUrl.fromLocalFile(path).toString()
        elif path and os.path.isfile(path):
            self._bg_mode = "image"
            self._bg_url = QUrl.fromLocalFile(path).toString()
        else:
            self._bg_mode = "gradient"
            self._bg_url = ""
        self._grad_color = game["color"]
        self._grad_char = game["char"]
        self.backgroundChanged.emit()
        self._refresh_task_card()

    def _load_bg(self, game: dict) -> str | None:
        """返回该脚本应使用的背景路径（自定义壁纸 → 脚本背景 → DEFAULT_BG）。

        文件不存在返回 None（走渐变）；扩展名由调用方分发（视频/图片）。
        """
        custom = self._wallpapers().get(game["script_name"])
        bg_path = custom or (_get_game_bg_img(game["script_name"]) or DEFAULT_BG)
        resolved = resolve_script_path(bg_path)
        if not os.path.isfile(resolved):
            return None
        return resolved

    def _wallpapers(self) -> dict:
        """读取 config/wallpaper.json（脚本 → 壁纸路径）；缺失返回空。"""
        import json

        path = resolve_script_path("config/wallpaper.json")
        if not os.path.isfile(path):
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ── 视频错误回退 ─────────────────────────────────────────────────────
    @Slot(str)
    def videoError(self, reason: str):
        """QML VideoOutput 媒体错误：回退渐变（QML 侧 MediaPlayer 触发）。"""
        import warnings

        warnings.warn(
            f"[qml] 视频背景不可用，回退：{reason or '媒体解码错误'}",
            RuntimeWarning,
            stacklevel=2,
        )
        self._bg_mode = "gradient"
        self._bg_url = ""
        self.backgroundChanged.emit()

    # ── 窗口控制 ─────────────────────────────────────────────────────────
    @Slot()
    def startWindowMove(self):
        """系统原生窗口拖动（Windows DWM 接管，最流畅）。

        QML 逐帧 move 会每帧重排场景图（2K 视频纹理重绘），导致拖动不跟手；
        系统接管后窗口表面由 DWM 搬移，不触发场景重绘，与普通窗口一致。
        """
        from PySide6.QtGui import QGuiApplication

        win = QGuiApplication.focusWindow()
        if win is not None:
            win.startSystemMove()

    @Slot()
    def minimize(self):
        app = self._app()
        if app is not None:
            app.focusWindow().showMinimized()

    @Slot()
    def closeWindow(self):
        app = self._app()
        if app is not None:
            app.quit()

    def _app(self):
        from PySide6.QtWidgets import QApplication

        return QApplication.instance()


# 供 context 共享的类型引用（QML 不直接实例化，仅为类型安全预留）
__all__ = ["QmlBridge", "ScriptIconProvider"]
