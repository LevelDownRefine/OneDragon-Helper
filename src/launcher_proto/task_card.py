"""launcher_proto 任务调度面板（TaskCardPanel）：专题卡构建与副本/周常交互。

从 launcher_proto.py 按职责拆分而来（2026-08-16）：卡片本体（标题行 + 总开关 +
日常/周常任务行）、副本级联菜单、周几选择、gui_state.json 持久化，全部收敛到
独立面板类。依赖单向：task_card → theme / widgets / config 模块，主窗口 → task_card。

与主窗口解耦方式：构造注入回调与共享状态——
- get_current_game：取当前选中游戏条目（主窗口持有索引）
- dungeon_state / weekly_toggle_state：gui_state.json 数据与周常开关内存态
  （dict 引用共享，面板读写后主窗口可见）
- service：ChainService（dungeon_map / save_ui_state）
- toast：提示浮层
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QMenu,
    QWidget,
)

from src.config.dungeon_config import get_display_name, parse_dungeon_config
from src.config.set_config import _CONFIGS
from src.config.set_config import supports_weekly as _supports_weekly
from src.launcher_proto.theme import (
    C_BLUE_TEXT,
    C_FAINT,
    C_WHITE,
    C_YELLOW,
    WEEKDAY_NAMES,
)
from src.launcher_proto.widgets import Toggle
from src.service.chain_service import ChainService
from src.utils_weekly import get_week_num, is_weekly_start_reached


class TaskCardPanel(QFrame):
    """专题卡面板：标题 + 总开关 + 日常/周常任务行（chip + toggle）。

    所有子控件（标题/总开关/分隔线/两行/chip/toggle）由面板自建自持；
    副本选择与周几起始日经回调读写共享状态并持久化到 gui_state.json。

    基类用 QFrame 而非 QWidget：QFrame 的样式表背景绘制路径可靠
    （QWidget 需额外属性，且与 QGraphicsDropShadowEffect 组合时背景会丢失）。
    """

    def __init__(
        self,
        parent,
        *,
        get_current_game: Callable[[], dict],
        dungeon_state: dict,
        weekly_toggle_state: dict[str, bool],
        service: ChainService,
        toast: Callable[[str], None],
    ):
        super().__init__(parent)
        self._get_current_game = get_current_game
        self._dungeon_state = dungeon_state
        self._weekly_toggle_state = weekly_toggle_state
        self._service = service
        self._toast = toast
        self._build_ui()

    def _current_game(self) -> dict:
        return self._get_current_game()

    def _build_ui(self):
        """专题卡（x:128 y:428 w:480，玻璃半透明）。

        标题随选中游戏变化；所有脚本都显示卡片（任务调度），未适配副本配置
        的游戏（不在 set_config._CONFIGS）只留标题，隐藏总开关/分隔线/任务行
        （通过 refresh 的 _set_task_rows_visible 控制，卡片高度随之收缩）。
        """
        self.setGeometry(128, 428, 480, 268)
        # 玻璃感：半透明（QFrame 默认绘制样式表背景）
        self.setStyleSheet("background:rgba(10,16,32,0.78); border-radius:16px;")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 130))
        self.setGraphicsEffect(shadow)
        self.show()

        # 标题行（ico 36×36 与任务行 ico 对齐：x=12；文字 x=58 与行名对齐）
        title_row = QWidget(self)
        title_row.setGeometry(20, 18, 440, 36)
        t_ico = QLabel("▶", title_row)
        t_ico.setGeometry(12, 0, 36, 36)
        t_ico.setStyleSheet(
            f"background:{C_YELLOW}; color:#1A1A1A; font-size:16px;"
            "border-radius:10px; qproperty-alignment:AlignCenter;"
        )
        self.task_title = QLabel("", title_row)
        self.task_title.setGeometry(58, 5, 260, 26)
        self.task_title.setStyleSheet(
            f"color:{C_WHITE}; font-size:19px; font-weight:700; background:transparent;"
        )

        # 总开关（标题行右侧，与任务行开关右边缘对齐 x=388；一键同步日常/周本）
        self.master_toggle = Toggle(True, title_row)
        self.master_toggle.move(388, 7)
        self.master_toggle.toggled.connect(self._on_master_toggled)

        # 分隔线
        self.card_divider = QFrame(self)
        self.card_divider.setGeometry(20, 56, 440, 1)
        self.card_divider.setStyleSheet("background:#2A3850;")

        # 日常行（启用；chip 点击弹出副本选择菜单）
        self.daily_row, self.daily_chip_lbl = self._task_row(
            20,
            68,
            "日常",
            "#0F1A2E",
            C_BLUE_TEXT,
            "⚡",
            "#1A3A7A",
            C_BLUE_TEXT,
            "选择副本",
            True,
        )
        self.daily_chip_lbl.setCursor(Qt.PointingHandCursor)
        self.daily_chip_lbl.mousePressEvent = lambda e: (
            self._show_daily_menu() if e.button() == Qt.LeftButton else None
        )
        # 周常行（周几以后开始执行；支持态由 _supports_weekly 决定，
        # 支持则 chip 可点选周一起始日，未支持保持「未支持」禁用）
        self.weekly_row, self.weekly_chip_lbl = self._task_row(
            20,
            134,
            "周常",
            "#1A2028",
            C_FAINT,
            "📅",
            "#2A3040",
            C_FAINT,
            "未支持",
            False,
            obj_prefix="weekly",
        )
        self.weekly_ico_lbl = self.weekly_row.findChild(QLabel, "weekly_ico")
        self.weekly_name_lbl = self.weekly_row.findChild(QLabel, "weekly_name")
        self.weekly_chip_lbl.setCursor(Qt.ArrowCursor)
        self.weekly_chip_lbl.mousePressEvent = lambda e: (
            self._show_weekly_menu() if e.button() == Qt.LeftButton else None
        )
        # 周常开关（toggle，纯内存 UI 态不持久化）：点击只改按钮，不写脚本配置；
        # 周常是否执行由运行链时 chain_gen 按 weekly_start 判断
        self.weekly_toggle = self.weekly_row.findChild(Toggle)
        self.weekly_toggle.toggled.connect(self._on_weekly_toggled)

    def refresh(self, game: dict):
        """切游戏后刷新：标题、任务行显隐、日常/周常 chip 与开关、背景。

        对齐旧 GUI _apply_current_game 的 task_card 部分。
        """
        adapted = game["script_name"] in _CONFIGS
        self._set_task_card_title(game["display_name"])
        self._set_task_rows_visible(adapted)
        if adapted:
            self._refresh_daily_chip()
            self._refresh_weekly_chip()
            self._sync_weekly_toggle()

    def _set_task_rows_visible(self, adapted: bool):
        """任务行显隐：适配脚本显示日常/周本（卡片 268 高）；未适配只留标题 + 总开关
        （隐藏分隔线/两行，卡片收缩到 100 高）。"""
        self.card_divider.setVisible(adapted)
        self.daily_row.setVisible(adapted)
        self.weekly_row.setVisible(adapted)
        height = 268 if adapted else 100
        self.setGeometry(128, 428, 480, height)

    def _set_task_card_title(self, display_name: str):
        """更新任务卡标题（只显示游戏名）。"""
        self.task_title.setText(display_name)

    def _task_row(
        self,
        x,
        y,
        name,
        chip_bg,
        name_fg,
        ico_char,
        ico_bg,
        chip_fg,
        chip_text,
        on,
        obj_prefix: str = "",
    ):
        """专题卡内任务行（56 高，图标+名称+chip+开关；行背景透明——画布已去）。

        ``obj_prefix`` 非空时给 ico/name/chip 子 QLabel 设
        ``{prefix}_ico/name/chip`` 的 objectName，供外部 ``findChild`` 拿到引用
        （如周常行支持态需同步切整行样式，日常行不需要）。

        Returns:
            (row, chip_lbl)：chip_lbl 供外部点击绑定副本选择菜单。
        """
        row = QFrame(self)
        row.setGeometry(x, y, 440, 56)
        row.setStyleSheet("background:transparent;")
        # 置灰由行内暗色参数表达（未支持行传暗色 chip/ico/文字 + toggle 灰色关闭态），
        # 不加覆盖层：QGraphicsOpacityEffect 会让子控件渲染偏移，覆盖层会叠出多余背景
        row.show()

        ico = QLabel(ico_char, row)
        ico.setGeometry(12, 10, 36, 36)
        ico.setStyleSheet(
            f"background:{ico_bg}; color:{chip_fg}; font-size:16px;"
            "border-radius:10px; qproperty-alignment:AlignCenter;"
        )
        if obj_prefix:
            ico.setObjectName(f"{obj_prefix}_ico")

        name_lbl = QLabel(name, row)
        name_lbl.setGeometry(58, 15, 60, 26)
        name_lbl.setStyleSheet(
            f"color:{name_fg}; font-size:15px; font-weight:600; background:transparent;"
        )
        if obj_prefix:
            name_lbl.setObjectName(f"{obj_prefix}_name")

        chip = QFrame(row)
        chip.setGeometry(130, 15, 96, 26)
        chip.setAttribute(Qt.WA_Hover, True)
        chip.setStyleSheet(
            f"QFrame {{ background:{chip_bg}; border-radius:13px; border:1px solid #33517A; }}"
            f"QFrame:hover {{ background:{QColor(chip_bg).lighter(125).name()};"
            " border:1px solid #7DA8FF; }"
        )
        chip_lbl = QLabel(chip_text, chip)
        chip_lbl.setStyleSheet(
            f"color:{chip_fg}; font-size:11px; background:transparent;"
        )
        chip_lbl.setGeometry(0, 0, 96, 26)
        chip_lbl.setAlignment(Qt.AlignCenter)
        if obj_prefix:
            chip_lbl.setObjectName(f"{obj_prefix}_chip")

        toggle = Toggle(on, row)
        toggle.move(388, 17)
        # toggle 关闭态自带灰色轨道/滑块视觉，行内容置灰由暗色参数表达，
        # 无需行级联动（避免 QGraphicsEffect 偏移 / 覆盖层叠出多余背景）
        return row, chip_lbl

    def _on_master_toggled(self, on):
        """总开关：一键同步日常/周本两个任务行开关（set_on 不发信号，无循环）。

        周常开关内存态一并同步（仅支持周常的脚本；总开关关 = 周常也关）。
        开关是纯内存态，不写脚本配置（由运行链时按 weekly_start 判断）。
        """
        for row in (self.daily_row, self.weekly_row):
            row.findChild(Toggle).set_on(on)
        script_name = self._current_game()["script_name"]
        if _supports_weekly(script_name):
            self._weekly_toggle_state[script_name] = on

    def _sync_weekly_toggle(self):
        """把当前游戏的周常开关内存态同步到 UI toggle（set_on 不发信号，无循环）。"""
        script_name = self._current_game()["script_name"]
        self.weekly_toggle.set_on(self._weekly_toggle_state.get(script_name, False))

    def _on_weekly_toggled(self, on: bool):
        """周常开关点击：只更新内存态（纯 UI，不持久化、不写脚本配置）。

        与日常开关模型一致：enabled 只在内存，周常是否执行由 weekly_start
        按「今天周几 >= 起始日」在运行链时决定（chain_gen → set_config）。
        """
        self._weekly_toggle_state[self._current_game()["script_name"]] = on

    def _show_daily_menu(self):
        """日常副本选择：弹出 dungeon_list.yml 级联菜单（一级副本 → 二级序列）。

        选择经 _set_daily 持久化到 gui_state.json；运行链时由
        generate_chain → set_config 写入脚本 config。
        """
        game = self._current_game()
        dungeon_cfg = self._service.dungeon_map().get(game["script_name"])
        options, seq_map, _ = parse_dungeon_config(dungeon_cfg)
        if not options:
            self._toast(f"{game['display_name']}：暂无副本选项")
            return
        menu = QMenu(self)
        menu.setStyleSheet("background:#0F1A2E; color:#FFFFFF;")
        for dungeon_name in options:
            if dungeon_name == "未选择":
                menu.addAction("未选择").triggered.connect(
                    lambda _c=False: self._set_daily(None, None)
                )
                menu.addSeparator()
                continue
            seqs = seq_map.get(dungeon_name, [])
            if seqs:
                submenu = menu.addMenu(dungeon_name)
                for display, value in seqs:
                    submenu.addAction(display).triggered.connect(
                        lambda _c=False, dn=dungeon_name, sq=value: self._set_daily(
                            dn, sq
                        )
                    )
            else:
                menu.addAction(dungeon_name).triggered.connect(
                    lambda _c=False, dn=dungeon_name: self._set_daily(dn, None)
                )
        menu.exec(
            self.daily_chip_lbl.mapToGlobal(self.daily_chip_lbl.rect().bottomLeft())
        )

    def _dungeon_chip_text(self, dungeon_cfg, dungeon_name: str, sequence) -> str:
        """副本 chip 文字：有二级序列且选了二级 → 二级展示名；否则副本名本身。

        避免 get_display_name 找不到二级匹配时返回字符串 "None"。
        """
        _, seq_map, _ = parse_dungeon_config(dungeon_cfg)
        if sequence is not None and dungeon_name in seq_map:
            return get_display_name(seq_map, dungeon_name, sequence)
        return dungeon_name

    def _refresh_daily_chip(self):
        """从 _dungeon_state（gui_state.json）恢复当前脚本的日常副本 chip 文字。"""
        game = self._current_game()
        saved = self._dungeon_state.get(game["script_name"])
        if not saved or not saved.get("dungeon"):
            self.daily_chip_lbl.setText("选择副本")
            return
        dungeon_cfg = self._service.dungeon_map().get(game["script_name"])
        self.daily_chip_lbl.setText(
            self._dungeon_chip_text(
                dungeon_cfg, saved["dungeon"], saved.get("sequence")
            )
        )

    def _refresh_weekly_chip(self):
        """刷新周常行整行样式：支持周常的脚本切到亮蓝可点，未支持保持暗色置灰。

        周常行整行（图标 + "周常"文字 + chip + toggle）必须在支持/未支持间整体切换，
        否则只有 chip 变亮、图标和文字仍暗，视觉割裂（之前 bug：支持态下整行
        仍像「未支持」）。切换点：refresh（切游戏）与 toggle 状态同步时。
        """
        game = self._current_game()
        supported = _supports_weekly(game["script_name"])
        saved = self._dungeon_state.get(game["script_name"])
        start_day = saved.get("weekly_start") if saved else None
        chip = self.weekly_chip_lbl.parent()
        if not supported:
            self.weekly_chip_lbl.setText("未支持")
            chip.setStyleSheet(
                "QFrame { background:#1A2028; border-radius:13px;"
                " border:1px solid #2A3850; }"
            )
            self.weekly_chip_lbl.setStyleSheet(
                f"color:{C_FAINT}; font-size:11px; background:transparent;"
            )
            self.weekly_chip_lbl.setCursor(Qt.ArrowCursor)
            self.weekly_toggle.setEnabled(False)
            self.weekly_ico_lbl.setStyleSheet(
                f"background:#2A3040; color:{C_FAINT}; font-size:16px;"
                "border-radius:10px; qproperty-alignment:AlignCenter;"
            )
            self.weekly_name_lbl.setStyleSheet(
                f"color:{C_FAINT}; font-size:15px; font-weight:600; background:transparent;"
            )
            return
        self.weekly_toggle.setEnabled(True)
        if start_day is None:
            self.weekly_chip_lbl.setText("选择周几")
        else:
            self.weekly_chip_lbl.setText(f"{WEEKDAY_NAMES[start_day]}起")
        chip.setStyleSheet(
            f"QFrame {{ background:#0F1A2E; border-radius:13px; border:1px solid #33517A; }}"
            f"QFrame:hover {{ background:{QColor('#0F1A2E').lighter(125).name()};"
            " border:1px solid #7DA8FF; }"
        )
        self.weekly_chip_lbl.setStyleSheet(
            f"color:{C_BLUE_TEXT}; font-size:11px; background:transparent;"
        )
        self.weekly_chip_lbl.setCursor(Qt.PointingHandCursor)
        self.weekly_ico_lbl.setStyleSheet(
            f"background:#1A3A7A; color:{C_BLUE_TEXT}; font-size:16px;"
            "border-radius:10px; qproperty-alignment:AlignCenter;"
        )
        self.weekly_name_lbl.setStyleSheet(
            f"color:{C_BLUE_TEXT}; font-size:15px; font-weight:600; background:transparent;"
        )

    def _show_weekly_menu(self):
        """周常起始日选择：弹出周一至周日菜单（含今天标注，凌晨 4 点为界）。

        选择经 _set_weekly 持久化到 gui_state.json 并同步周常开关（UI 显示）；
        脚本配置的周常开关由运行链时 chain_gen 按 weekly_start 判断写入。
        """
        game = self._current_game()
        if not _supports_weekly(game["script_name"]):
            return
        menu = QMenu(self)
        menu.setStyleSheet("background:#0F1A2E; color:#FFFFFF;")
        today = get_week_num() + 1  # 0=周一..6=周日 → 1..7
        for day in range(1, 8):
            label = WEEKDAY_NAMES[day]
            if day == today:
                label += "（今天）"
            menu.addAction(label).triggered.connect(
                lambda _c=False, d=day: self._set_weekly(d)
            )
        menu.exec(
            self.weekly_chip_lbl.mapToGlobal(self.weekly_chip_lbl.rect().bottomLeft())
        )

    def _set_weekly(self, start_day: int):
        """保存周常起始日（持久化到 gui_state.json 的 weekly_start，1=周一）并更新 chip。

        修改后立即同步周常开关（UI 显示）：今天周几 >= 起始日 → 开关开启，否则关闭。
        开关是纯内存态；脚本配置的周常开关由运行链时 chain_gen 按 weekly_start
        判断写入（与日常开关模型一致）。
        """
        assert start_day in WEEKDAY_NAMES, f"[task_card] 非法周几: {start_day}"
        game = self._current_game()
        saved = self._dungeon_state.setdefault(game["script_name"], {})
        saved["weekly_start"] = start_day
        self.weekly_chip_lbl.setText(f"{WEEKDAY_NAMES[start_day]}起")
        enabled = is_weekly_start_reached(start_day)
        self._weekly_toggle_state[game["script_name"]] = enabled
        self.weekly_toggle.set_on(enabled)
        self._service.save_ui_state(self._dungeon_state)

    def _set_daily(self, dungeon_name: str | None, sequence):
        """保存日常副本选择（持久化到 gui_state.json，与旧 GUI 一致）并更新 chip 文字。

        合并更新脚本条目（保留 weekly_start 等其它字段，不整体覆盖）。
        """
        game = self._current_game()
        saved = self._dungeon_state.setdefault(game["script_name"], {})
        if dungeon_name is None:
            saved.pop("dungeon", None)
            saved.pop("sequence", None)
            self.daily_chip_lbl.setText("选择副本")
        else:
            saved["dungeon"] = dungeon_name
            saved["sequence"] = sequence
            dungeon_cfg = self._service.dungeon_map().get(game["script_name"])
            self.daily_chip_lbl.setText(
                self._dungeon_chip_text(dungeon_cfg, dungeon_name, sequence)
            )
        self._service.save_ui_state(self._dungeon_state)

    def enabled_task_names(self) -> list:
        """当前已启用（开关开启）的任务行名称。"""
        return [
            n
            for n, row in (("日常", self.daily_row), ("周常", self.weekly_row))
            if row.findChild(Toggle).is_on()
        ]
