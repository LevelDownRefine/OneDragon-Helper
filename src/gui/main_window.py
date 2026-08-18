"""OneDragon-Helper 启动器式 GUI（接入真实 ChainService 数据）。

画布：1280x720 (16:9) · 无系统标题栏（frameless，按住空白处可拖动窗口）
运行：项目根下 `python -m src.gui.main_window`（模块方式，
  项目根在 sys.path，直接 import src.*）。
数据源：ChainService.load_config() 的 script_list（左侧栏 = 全部脚本，含 python
  辅助脚本）；set_config.is_adapted 决定该脚本是否有「任务卡」适配；
  get_game_exe_path() 供「打开游戏」。背景图经 set_config.get_game_bg_img()
  获取（ScriptConfig.bg_img 相对脚本根目录声明，接口解析为绝对路径并校验存在）；
  B站链接经 set_config.get_game_bilibili() 获取（ScriptConfig.bilibili 声明，
  各游戏官方 B 站空间）；GitHub 链接经 set_config.get_game_github() 获取
  （ScriptConfig.github 声明，各脚本项目主页）；未配置的走通用占位链接。
结构：
  左侧游戏栏(80x720，脚本图标 + ⊞ + 启动全部整体可滚轮/拖动滚动)
   + HERO区(1280x720，按选中游戏画背景：官方图或渐变占位)
  右上：窗口控制（最小化/关闭）
  左下：专题卡（选中游戏的任务调度，日常/周本两行；未适配游戏隐藏）
  右下：启动脚本蓝色大胶囊（单脚本直跑；右侧 ☰ 弹配置）
  右侧：悬浮图标条（主页/启动游戏/文件夹/B站/GitHub，无背景框）
"""

import json
import os
import subprocess
import sys
import webbrowser

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QMessageBox,
    QWidget,
)

from src.config.set_config import ScriptConfig
from src.config.set_config import get_game_bg_img as _get_game_bg_img
from src.config.set_config import get_game_bilibili as _get_game_bilibili
from src.config.set_config import get_game_exe_path as _get_game_exe_path
from src.config.set_config import get_game_github as _get_game_github
from src.config.set_config import get_game_homepage as _get_game_homepage
from src.config.set_config import supports_weekly as _supports_weekly
from src.config.subscript import get_script_name, resolve_script_path
from src.gui.dialogs import SingleScriptConfigDialog, confirm_config_update
from src.gui.icons import (
    GlyphButton,
    IconButton,
    draw_add,
    draw_close,
    draw_config,
    draw_controller,
    draw_deselect_all,
    draw_folder,
    draw_github,
    draw_grid,
    draw_home,
    draw_launch,
    draw_min,
    draw_select_all,
    draw_tv,
    draw_wallpaper,
)
from src.gui.task_card import TaskCardPanel
from src.gui.theme import (
    _URL_BILIBILI,
    _URL_HOME,
    C_BLUE,
    C_BLUE_DEEP,
    C_BTN_DARK,
    C_GAME_DIM,
    C_GREEN,
    C_WHITE,
    C_WINDOW_BG,
    C_YELLOW,
    CANVAS_H,
    CANVAS_W,
    DEFAULT_BG,
    FONT_FAMILY,
    make_font,
    rgba,
)
from src.gui.video_backdrop import VideoBackdrop, is_video
from src.gui.widgets import GameIcon, RailContainer
from src.service.chain_service import ChainService
from src.utils import get_config_yml_path_under_root
from src.utils_runner import build_script_command
from src.utils_weekly import is_weekly_start_reached


# ═══════════════════════ 主窗口 ════════════════════════════════════════════
class LauncherWindow(QWidget):
    def __init__(self):
        super().__init__()
        # 无系统标题栏（画布无顶部栏，窗口控制自绘在右上角）；按住空白处可拖动窗口
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setFixedSize(CANVAS_W, CANVAS_H)
        self.setWindowTitle("OneDragon-Helper · 游戏自动化调度器")
        self._drag_offset = None
        self.service = ChainService()
        self.games = self._load_games()
        assert self.games, "[main_window] config.yml 中没有脚本"
        self._current_index = 0
        self._control_mode = (
            False  # ⊞ 模式：False=浏览（点图标选脚本），True=控制（点图标启停）
        )
        # 任务调度（副本/序列选择）持久化到 gui_state.json（与旧 GUI 一致）；
        # 仅 enabled 按钮状态不持久化（内存态，重启默认全开）
        self._dungeon_state: dict = self.service.load_ui_state()
        self._weekly_toggle_state: dict[str, bool] = self._init_weekly_toggle_states()
        self._custom_bg: dict[str, str] = self._load_wallpapers()  # 脚本 → 壁纸路径
        # 背景状态：图片/渐变由本窗口 paintEvent 绘制（零回归）；视频懒创建
        # VideoBackdrop（QQuickWidget 场景图合成，不建系统 Overlay、不盖 UI）
        self._bg = QPixmap()
        self._grad_color = C_GAME_DIM
        self._grad_char = ""
        self._video_active = False  # 视频模式：paintEvent 只铺底色兜底
        self._video_backdrop: VideoBackdrop | None = None
        self._build_ui()
        self._apply_current_game()
        # 周常开关（enabled）是纯内存态：启动时由 weekly_start 初始化（_init_weekly_toggle_states），
        # 脚本配置的周常开关由运行链时 chain_gen 按 weekly_start 判断写入，启动时不落盘

    def _init_weekly_toggle_states(self) -> dict[str, bool]:
        """初始化各脚本周常开关（纯内存 UI 态，不持久化、不写脚本配置）。

        启动时由 weekly_start 决定：已设置「周几起」且今天周几 >= 起始日 → True，
        否则 False。仅用于 UI 显示；周常是否执行由运行链时 chain_gen 按
        weekly_start 判断（与日常开关模型一致）。
        """
        states: dict[str, bool] = {}
        for game in self.games:
            script_name = game["script_name"]
            if not _supports_weekly(script_name):
                continue
            saved = self._dungeon_state.get(script_name)
            weekly_start = saved.get("weekly_start") if saved else None
            states[script_name] = weekly_start is not None and is_weekly_start_reached(
                weekly_start
            )
        return states

    def _load_games(self) -> list[dict]:
        """从 config.yml 构建左侧栏脚本列表（全部 script_list，含 python 辅助脚本）。

        Returns:
            每个元素：{display_name, script_name, script_data, char, color}。
            script_data 供 get_script_icon 取真实图标；color/char 仅供兜底渐变背景。
        """
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
        return games

    def _apply_current_game(self):
        """选中游戏切换后：刷新任务卡（所有脚本都显示，未适配只留标题）、
        日常 chip、周常 chip 与开关、背景图。"""
        game = self.games[self._current_index]
        self.task_card.refresh(game)
        bg_path = self._load_bg(game)
        self._set_background(bg_path, color=game["color"], char=game["char"])

    def _set_background(self, path: str | None, *, color=None, char: str = ""):
        """按路径分流：视频走 VideoBackdrop（QQuickWidget 场景图合成，不盖 UI），
        图片/缺失走本窗口 paintEvent（cover 裁剪 / 渐变占位，零回归）。"""
        if path and is_video(path):
            if os.path.isfile(path):
                self._show_video_backdrop(path)
                return
            path = None  # 视频文件缺失 → 走渐变
        self._hide_video_backdrop()
        self._bg = QPixmap(path) if path else QPixmap()
        self._grad_color = color or C_GAME_DIM
        self._grad_char = char
        self.update()

    def _show_video_backdrop(self, path: str):
        """懒创建并显示视频背景层（放最底，hero/rail 叠其上）。"""
        if self._video_backdrop is None:
            self._video_backdrop = VideoBackdrop(self)
            self._video_backdrop.setGeometry(0, 0, CANVAS_W, CANVAS_H)
            # Windows 需显式创建句柄初始化 EGL 上下文（否则视频首帧黑屏）；
            # 启动即视频背景时走 showEvent，切游戏/换壁纸时在此调用
            self._video_backdrop.winId()
            self._video_backdrop.lower()
            self._video_backdrop.fallback_requested.connect(self._on_video_fallback)
        self._video_active = True
        self._video_backdrop.setGeometry(0, 0, CANVAS_W, CANVAS_H)
        self._video_backdrop.play(path)

    def _hide_video_backdrop(self):
        """停止并隐藏视频背景层（切图片/渐变时）。"""
        self._video_active = False
        if self._video_backdrop is not None:
            self._video_backdrop.stop()

    def _on_video_fallback(self, reason: str):
        """视频背景不可用：回退到当前游戏的渐变占位。"""
        assert self._current_index >= 0, "[main_window] 视频回退时无选中脚本"
        game = self.games[self._current_index]
        self._set_background(None, color=game["color"], char=game["char"])

    def _load_bg(self, game: dict) -> str | None:
        """返回该游戏应使用的背景路径：自定义壁纸（_open_wallpaper）→
        脚本背景（set_config）→ 兜底 assets/ds.jpg。

        文件不存在返回 None，由主窗口走渐变占位。视频/图片扩展名都走
        同一路径返回；调用方按扩展名分发。
        """
        bg_path = self._custom_bg.get(game["script_name"]) or (
            _get_game_bg_img(game["script_name"]) or DEFAULT_BG
        )
        resolved = resolve_script_path(bg_path)
        if not os.path.isfile(resolved):
            return None
        return resolved

    # ── 无边框窗口拖动（按住空白处移动窗口）─────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    # ── 背景绘制（视频由 VideoBackdrop 场景图合成铺满；图片/渐变在此绘制）──
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), QColor(C_WINDOW_BG))
        if self._video_active:
            return  # 视频由 VideoBackdrop 铺满显示，本窗口只铺底色兜底
        if not self._bg.isNull():
            self._draw_cover(p, self.rect())
        else:
            self._draw_gradient(p, self.rect())

    def _draw_cover(self, p: QPainter, target: QRect):
        """cover 裁剪绘制：按目标比例截取源图中心，避免超宽/超高图拉伸变形。"""
        src_w, src_h = self._bg.width(), self._bg.height()
        target_ratio = target.width() / target.height()
        src_ratio = src_w / src_h
        if src_ratio > target_ratio:
            crop_w = int(src_h * target_ratio)
            src_rect = QRect((src_w - crop_w) // 2, 0, crop_w, src_h)
        else:
            crop_h = int(src_w / target_ratio)
            src_rect = QRect(0, (src_h - crop_h) // 2, src_w, crop_h)
        p.drawPixmap(target, self._bg, src_rect)

    def _draw_gradient(self, p: QPainter, rect: QRect):
        base = QColor(self._grad_color)
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, base.lighter(130))
        grad.setColorAt(1.0, QColor(C_WINDOW_BG))
        p.fillRect(rect, grad)
        p.setFont(make_font(260, 900))
        p.setPen(QColor(255, 255, 255, 22))
        p.drawText(rect, Qt.AlignCenter, self._grad_char)

    def showEvent(self, event):
        super().showEvent(event)
        if self._video_backdrop is not None:
            # Windows 需显式创建句柄以初始化 EGL 上下文（否则视频首帧黑屏）
            self._video_backdrop.winId()
            self._video_backdrop.setGeometry(0, 0, CANVAS_W, CANVAS_H)

    # ── UI 构建 ──────────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_left_rail()
        self._build_hero()
        self._build_task_card()
        self._build_launch_button()
        self._build_select_buttons()
        self._build_float_bar()
        self._build_window_controls()
        self._build_toast()
        # hero 全画布（后创建）会盖住 rail，最后统一把 rail 提到最上保证可交互
        self.rail.raise_()

    def _build_toast(self):
        """右下角 toast 浮层（frameless 窗口无标题栏，提示必须用浮层显示）。"""
        self.toast_lbl = QLabel(self)
        self.toast_lbl.setStyleSheet(
            "background:rgba(10,16,32,0.92); color:#FFFFFF;"
            "border-radius:12px; padding:10px 18px; font-size:14px;"
        )
        self.toast_lbl.hide()
        self.toast_lbl.raise_()
        # 单实例 timer：连续触发时 restart，避免旧 timer 提前隐藏新 toast
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast_lbl.hide)

    def _build_left_rail(self):
        """左侧游戏栏：脚本图标可滚动（滚轮/拖动，无 scrollbar）；
        ⊞ 与启动全部固定在栏底（画布 3:33/3:151 常驻最下方）。"""
        # 底部固定区（贴底，底部间距 16）：启动全部 48 + 8 + ⊞ 48 + 8 + 分割线 1 = 113
        self.rail = RailContainer(self, fixed_bottom_height=113)
        self.rail.move(0, 0)
        # hero 全画布后覆盖 rail 区域（0..80），raise 让 rail 浮在最上（可交互）
        self.rail.raise_()
        # 显式 show：首次构建时窗口未显示可省略，但拖拽重排（窗口已显示）重建时
        # 新建 QWidget 默认隐藏，不 show 会导致整个左侧栏消失
        self.rail.show()
        content = self.rail.content()

        # 脚本图标（滚动区，56×56 stride 64（含 8 间距，画布 itemSpacing=8）；
        # rail.add() 触发滚动范围重算；x=12 在 80 宽栏内居中）
        # 重建前收集旧图标启用状态（按 script_name）：保存配置/增删脚本后重建 rail
        # 不重置用户启停；首次构建（game_icons 不存在）或新增脚本默认启用（全开语义）
        prev_enabled = (
            {icon._script_name for icon in self.game_icons if icon.is_enabled()}
            if hasattr(self, "game_icons")
            else None
        )
        self.game_icons = []
        for i, game in enumerate(self.games):
            icon = GameIcon(
                i,
                game["script_name"],
                game["script_data"],
                i == self._current_index,
                enabled=(prev_enabled is None or game["script_name"] in prev_enabled),
                parent=content,
            )
            self.rail.add(icon, 12, 16 + i * 64)
            icon.clicked.connect(self._select_game)
            icon.dropped.connect(self._reorder_scripts)
            self.game_icons.append(icon)

        # 固定区遮罩：z-order 在 content 之上、固定区元素之下——滚动内容显示到
        # 分割线以下就被盖住，不会透过 ⊞（透明背景）与 ▶ 区域造成"重合"。
        # 必须完全不透明：半透明会把滚过的图标透出来。
        self._fixed_overlay = QFrame(self.rail)
        self._fixed_overlay.setGeometry(0, 591, 80, CANVAS_H - 591)
        self._fixed_overlay.setStyleSheet("background:#070A14;")
        self._fixed_overlay.show()

        # 分割线（⊞ 上方 8px，固定区顶；与画布 10:5 一致）
        divider = QFrame(self.rail)
        divider.setGeometry(16, 591, 48, 1)
        divider.setStyleSheet("background:#2A3850;")
        divider.show()

        # ⊞ 工具网格（固定：y=600；48×48；点击切换浏览/控制模式）
        self.grid_frame = QFrame(self.rail)
        self.grid_frame.setGeometry(16, 600, 48, 48)
        self.grid_frame.setStyleSheet(
            "background:transparent; border:1px solid #4D6A8C; border-radius:12px;"
        )
        self.grid_frame.setCursor(Qt.PointingHandCursor)
        self.grid_frame.mousePressEvent = lambda e: (
            self._toggle_mode() if e.button() == Qt.LeftButton else None
        )
        grid_glyph = GlyphButton(draw_grid, self.grid_frame)
        grid_glyph.setGeometry(0, 0, 48, 48)
        grid_glyph.show()
        self.grid_frame.show()

        # 启动全部按钮（固定最底部：y=656；48×48；QFrame + WA_Hover 启用 :hover 反馈）
        launch_btn = QFrame(self.rail)
        launch_btn.setGeometry(16, 656, 48, 48)
        launch_btn.setAttribute(Qt.WA_Hover, True)
        launch_btn.setStyleSheet(
            f"QFrame {{ background:{C_YELLOW}; border-radius:12px; }}"
            f"QFrame:hover {{ background:{QColor(C_YELLOW).lighter(118).name()}; }}"
        )
        launch_btn.setCursor(Qt.PointingHandCursor)
        launch_glyph = GlyphButton(draw_launch, launch_btn)
        launch_glyph.setGeometry(0, 0, 48, 48)
        launch_glyph.show()
        launch_btn.show()

        # 点击事件（accept 防止冒泡触发 RailContainer 拖动）
        def _on_launch_press(e):
            if e.button() == Qt.LeftButton:
                e.accept()
                self._launch_all()

        launch_btn.mousePressEvent = _on_launch_press
        # 固定区元素直接放 rail 上，滚动只影响 content；重建后恢复 ⊞ 模式样式
        self._apply_mode_style()

    def _rebuild_left_rail(self):
        """（重）建左侧栏：销毁旧 rail 后按 self.games 重建（脚本增删/改名后调用）。

        旧 rail 先 setParent(None) 脱离显示，再 deleteLater 排队销毁；
        _build_left_rail 内 self.rail / self.game_icons 均重新赋值。
        """
        if getattr(self, "rail", None) is not None:
            self.rail.setParent(None)
            self.rail.deleteLater()
        self._build_left_rail()

    def _apply_mode_style(self):
        """刷新 ⊞ 的模式样式（浏览/控制），供 _toggle_mode 与重建后恢复用。

        控制模式：⊞ 高亮 + 显示全选/清空按钮；浏览模式：⊞ 常态 + 隐藏。
        _build_left_rail 重建时 _build_select_buttons 尚未创建，getattr 保护。
        """
        if self._control_mode:
            self.grid_frame.setStyleSheet(
                "background:#1A2A4A; border:1px solid #7DA8FF; border-radius:14px;"
            )
        else:
            self.grid_frame.setStyleSheet(
                "background:transparent; border:1px solid #4D6A8C; border-radius:14px;"
            )
        for attr in ("clear_btn", "select_all_btn", "add_btn"):
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.setVisible(self._control_mode)

    def _build_hero(self):
        """HERO 区：全画布 1280x720（子元素用画布绝对坐标）。

        背景图由 LauncherWindow.paintEvent 铺满全画布（16:9 零裁切）；视频帧
        也由 paintEvent 经 QVideoSink 取帧后当普通位图绘制（UI 在其上叠加）。
        hero 只是子元素容器（透明），坐标与画布绝对坐标一致。"""
        self.hero = QWidget(self)
        self.hero.setGeometry(0, 0, CANVAS_W, CANVAS_H)

    def _build_task_card(self):
        """专题卡（左下，玻璃半透明）：装配 TaskCardPanel。

        面板自持全部子控件与交互（副本/周常菜单、gui_state 持久化），
        主窗口只注入回调与共享状态。
        """
        self.task_card = TaskCardPanel(
            self.hero,
            get_current_game=self._current_game,
            dungeon_state=self._dungeon_state,
            weekly_toggle_state=self._weekly_toggle_state,
            service=self.service,
            toast=self._toast,
        )
        self.task_card.show()

    def _build_launch_button(self):
        """启动脚本：右下蓝色大胶囊（x:960 y:636 w:216 h:64）——可点击。

        内部布局：▶ 圆 56×56 占满高度 + 文字居中 + ☰ 圆 56×56 对称。
        文字 x=60 宽 96，中心 108 = (60+156)/2，正好在 ▶ 和 ☰ 的几何中点。"""
        btn = QFrame(self.hero)
        btn.setGeometry(960, 636, 216, 64)
        btn.setAttribute(Qt.WA_Hover, True)
        btn.setStyleSheet(
            f"QFrame {{ background:{C_BLUE}; border-radius:32px; }}"
            f"QFrame:hover {{ background:{QColor(C_BLUE).lighter(118).name()}; }}"
        )
        btn.setCursor(Qt.PointingHandCursor)
        shadow = QGraphicsDropShadowEffect(btn)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 0)
        shadow.setColor(rgba("#2196F3", 110))
        btn.setGraphicsEffect(shadow)
        btn.show()

        # 左侧 ▶ 圆（56×56，占满按钮高度仅留 4 padding）
        play = QFrame(btn)
        play.setGeometry(4, 4, 56, 56)
        play.setStyleSheet(f"background:{C_BLUE_DEEP}; border-radius:28px;")
        play_ico = QLabel("▶", play)
        play_ico.setStyleSheet(
            f"color:{C_WHITE}; font-size:30px; font-weight:700; background:transparent;"
        )
        play_ico.setGeometry(0, 0, 56, 56)
        play_ico.setAlignment(Qt.AlignCenter)

        # 中间文字"启动脚本"居中于 [60, 156] 几何中点 108
        txt = QLabel("启动脚本", btn)
        txt.setGeometry(60, 0, 96, 64)
        txt.setStyleSheet(
            f"color:{C_WHITE}; font-size:18px; font-weight:700; background:transparent;"
        )
        txt.setAlignment(Qt.AlignCenter)

        # 右侧 ☰ 菜单圆（与 ▶ 对称，56×56）——点击打开当前脚本配置弹窗
        menu = QFrame(btn)
        menu.setGeometry(156, 4, 56, 56)
        menu.setStyleSheet(f"background:{C_BLUE_DEEP}; border-radius:28px;")
        menu.setCursor(Qt.PointingHandCursor)
        menu_ico = QLabel("≡", menu)
        menu_ico.setStyleSheet(
            f"color:{C_WHITE}; font-size:30px; background:transparent;"
        )
        menu_ico.setGeometry(0, 0, 56, 56)
        menu_ico.setAlignment(Qt.AlignCenter)

        def _on_menu_press(e):
            if e.button() == Qt.LeftButton:
                e.accept()  # 阻止冒泡到 btn 触发"启动脚本"
                self._open_config_dialog()

        menu.mousePressEvent = _on_menu_press

        # 点击 accept，防止事件冒泡到 LauncherWindow 触发窗口拖动
        def _on_launch_script_press(e):
            if e.button() == Qt.LeftButton:
                e.accept()
                self._launch_script()

        btn.mousePressEvent = _on_launch_script_press

    def _build_select_buttons(self):
        """添加 / 全选 / 清空按钮：清空在 ⊞ 右边（hero 区），全选在启动脚本胶囊右边。

        清空按钮：48x48 暗色圆角（× 图标），紧邻 rail 右边 8px（x=88, y=600），
        与 ⊞（y=600）水平对齐。点击 → _deselect_all（所有脚本停用）。

        添加按钮：48x48 暗色圆角（+ 图标），在清空按钮上方 8px（x=88, y=544），
        同一列垂直排列。点击 → _add_script（选文件追加脚本，对齐旧 GUI）。

        全选按钮：64x64 绿色圆角（√ 图标），紧邻启动脚本胶囊右边 8px
        （x=1184, y=636），与启动脚本（y=636）水平对齐。点击 → _select_all。
        """
        # 添加按钮（hero 区，清空按钮上方：x=88 y=544，48×48 与清空/全选同一列）
        self.add_btn = QFrame(self.hero)
        self.add_btn.setGeometry(88, 544, 48, 48)
        self.add_btn.setAttribute(Qt.WA_Hover, True)
        self.add_btn.setStyleSheet(
            f"QFrame {{ background:{C_BTN_DARK}; border-radius:14px; }}"
            f"QFrame:hover {{ background:{QColor(C_BTN_DARK).lighter(140).name()}; }}"
        )
        self.add_btn.setCursor(Qt.PointingHandCursor)
        add_glyph = GlyphButton(draw_add, self.add_btn)
        add_glyph.setGeometry(0, 0, 48, 48)
        add_glyph.show()
        self.add_btn.setVisible(self._control_mode)  # 仅控制模式显示

        def _on_add_press(e):
            if e.button() == Qt.LeftButton:
                e.accept()
                self._add_script()

        self.add_btn.mousePressEvent = _on_add_press

        # 清空按钮（hero 区，⊞ 右边）
        self.clear_btn = QFrame(self.hero)
        self.clear_btn.setGeometry(88, 600, 48, 48)
        self.clear_btn.setAttribute(Qt.WA_Hover, True)
        self.clear_btn.setStyleSheet(
            f"QFrame {{ background:{C_BTN_DARK}; border-radius:14px; }}"
            f"QFrame:hover {{ background:{QColor(C_BTN_DARK).lighter(140).name()}; }}"
        )
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        clear_glyph = GlyphButton(draw_deselect_all, self.clear_btn)
        clear_glyph.setGeometry(0, 0, 48, 48)
        clear_glyph.show()
        self.clear_btn.setVisible(self._control_mode)  # 仅控制模式显示

        def _on_clear_press(e):
            if e.button() == Qt.LeftButton:
                e.accept()
                self._deselect_all()

        self.clear_btn.mousePressEvent = _on_clear_press

        # 全选按钮（启动全部按钮右边：x=88 y=656，48×48 与启动全部对齐；
        # 清空按钮在 ⊞ 右边同一列 x=88 y=600，两者垂直排列）
        self.select_all_btn = QFrame(self.hero)
        self.select_all_btn.setGeometry(88, 656, 48, 48)
        self.select_all_btn.setAttribute(Qt.WA_Hover, True)
        self.select_all_btn.setStyleSheet(
            f"QFrame {{ background:{C_GREEN}; border-radius:12px; }}"
            f"QFrame:hover {{ background:{QColor(C_GREEN).lighter(115).name()}; }}"
        )
        self.select_all_btn.setCursor(Qt.PointingHandCursor)
        select_glyph = GlyphButton(draw_select_all, self.select_all_btn)
        select_glyph.setGeometry(0, 0, 48, 48)
        select_glyph.show()
        self.select_all_btn.setVisible(self._control_mode)  # 仅控制模式显示

        def _on_select_all_press(e):
            if e.button() == Qt.LeftButton:
                e.accept()
                self._select_all()

        self.select_all_btn.mousePressEvent = _on_select_all_press

    def _build_float_bar(self):
        """右侧悬浮条（6 个图标，无背景框——画布 3:287 已去玻璃底）。"""
        bar = QFrame(self.hero)
        bar.setGeometry(1220, 80, 60, 300)
        # 去掉玻璃底：图标按钮自身有深色底，直接悬浮在 hero 上
        bar.setStyleSheet("background:transparent;")
        bar.show()

        icons = [
            (draw_home, "主页", self._open_home),
            (draw_controller, "启动游戏", self._launch_game),
            (draw_folder, "打开脚本目录", self._open_script_folder),
            (draw_tv, "B站", self._open_bilibili),
            (draw_github, "GitHub", self._open_github),
            (draw_wallpaper, "壁纸", self._open_wallpaper),
        ]
        y = 22
        for fn, _name, action in icons:
            btn = IconButton(fn, bar, size=36, radius=12)
            btn.move(12, y)
            btn.clicked.connect(action)
            y += 48  # 36 + 12 gap

    def _build_window_controls(self):
        """窗口控制（右上角贴右边缘，深底圆按钮）。

        最右：关闭（1244..1280）；左 8px：最小化（1200..1236）；再左 8px：
        配置文件齿轮（1156..1192，打开总配置 config.yml——旧 GUI 同功能）。
        """
        cfg_btn = IconButton(draw_config, self.hero, size=36, radius=18)
        cfg_btn.move(1156, 8)
        cfg_btn.clicked.connect(self._open_config_yml)
        min_btn = IconButton(draw_min, self.hero, size=36, radius=18)
        min_btn.move(1200, 8)
        min_btn.clicked.connect(self.showMinimized)
        close_btn = IconButton(draw_close, self.hero, size=36, radius=18)
        close_btn.move(1244, 8)
        close_btn.clicked.connect(self.close)

    def _open_config_yml(self):
        """打开总配置文件 config.yml（系统默认程序）；缺失时 toast 提示（对齐旧 GUI）。"""
        config_path = get_config_yml_path_under_root()
        if not os.path.isfile(config_path):
            self._toast("未找到 config/config.yml")
            return
        os.startfile(config_path)  # noqa: S606 打开配置文件

    # ── 交互 ─────────────────────────────────────────────────────────────
    def _toggle_mode(self):
        """⊞ 模式切换：浏览（点图标选脚本）⇄ 控制（点图标切换启用/停用）。"""
        self._control_mode = not self._control_mode
        self._apply_mode_style()
        if self._control_mode:
            self._toast("控制模式：点击图标切换启用/停用")
        else:
            self._toast("浏览模式：点击图标选择脚本")

    def _add_script(self):
        """弹出文件选择框，选完后追加脚本到 config.yml 并重建左侧栏（对齐旧 GUI）。

        复用旧 GUI 逻辑：选文件 → ScriptService.build_script_entry 构造条目（去重
        命名 + 类型推断 + 默认字段）→ ChainService.add_script 落盘 → 重建 rail。
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择脚本文件",
            "",
            "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)",
        )
        if not file_path:
            return

        file_path = os.path.normpath(file_path)
        existing = {g["script_name"] for g in self.games}
        script_data = self.service._script_service.build_script_entry(
            file_path, existing
        )
        self.service.add_script(script_data)
        self._reload_games()
        self._toast(f"已添加 {script_data['display_name']}")

    def _select_all(self):
        """全选：所有脚本图标设为启用（纯内存态，不持久化）。"""
        for icon in self.game_icons:
            icon.set_enabled(True)
        self._toast("已全选（全部启用）")

    def _deselect_all(self):
        """清空：所有脚本图标设为停用（纯内存态，不持久化）。"""
        for icon in self.game_icons:
            icon.set_enabled(False)
        self._toast("已清空（全部停用）")

    def _select_game(self, index: int):
        """点击左侧脚本图标：控制模式切换启停，浏览模式切换选中。"""
        assert 0 <= index < len(self.games), f"game index out of range: {index}"
        if self._control_mode:
            icon = self.game_icons[index]
            icon.set_enabled(not icon.is_enabled())
            self._toast(
                f"{self.games[index]['display_name']}："
                f"{'启用' if icon.is_enabled() else '停用'}"
            )
            return
        self._current_index = index
        for i, icon in enumerate(self.game_icons):
            icon.set_selected(i == index)
        self._apply_current_game()
        self._toast(f"已切换到 {self.games[index]['display_name']}")

    def _current_game(self) -> dict:
        """当前选中游戏条目。"""
        return self.games[self._current_index]

    def _reorder_scripts(self, src_script_name: str, dst_script_name: str):
        """拖拽重排：把 src 脚本移到 dst 脚本位置，同步 UI 与 config.yml（对齐旧 GUI）。"""
        src_idx = next(
            (
                i
                for i, g in enumerate(self.games)
                if g["script_name"] == src_script_name
            ),
            None,
        )
        dst_idx = next(
            (
                i
                for i, g in enumerate(self.games)
                if g["script_name"] == dst_script_name
            ),
            None,
        )
        assert src_idx is not None, f"[main_window] 拖拽源脚本不存在: {src_script_name}"
        assert dst_idx is not None, (
            f"[main_window] 拖拽目标脚本不存在: {dst_script_name}"
        )
        cur_name = self._current_game()["script_name"]  # 重排后按名字恢复选中
        game = self.games.pop(src_idx)
        self.games.insert(dst_idx, game)

        # 同步 config.yml 顺序（以 UI 顺序为准），持久化
        config_data = self.service.load_config()
        scripts = config_data["script_list"]
        s_idx = next(
            (i for i, s in enumerate(scripts) if get_script_name(s) == src_script_name),
            None,
        )
        assert s_idx is not None, (
            f"[main_window] config 中找不到源脚本: {src_script_name}"
        )
        script = scripts.pop(s_idx)
        scripts.insert(dst_idx, script)
        self.service.save_config(config_data)

        # 重建左侧栏并恢复选中（新 index 可能已变）
        new_idx = next(
            (i for i, g in enumerate(self.games) if g["script_name"] == cur_name),
            None,
        )
        assert new_idx is not None, f"[main_window] 重排后丢失选中脚本: {cur_name}"
        self._current_index = new_idx
        self._rebuild_left_rail()
        self._apply_current_game()
        self._toast("已调整脚本顺序")

    def _confirm_run(self, enabled_keys: set[str]) -> bool:
        """运行前校验（对齐旧 GUI _warn_if_invalid_scripts）+ 确认弹窗。

        Returns:
            True 继续运行，False 取消。
        """
        config_data = self.service.load_config()
        enabled_scripts = [
            s for s in config_data["script_list"] if get_script_name(s) in enabled_keys
        ]
        invalid = self.service.collect_invalid_scripts(enabled_scripts)
        if invalid:
            details = "\n".join(f"· {name}：{msg}" for name, msg in invalid)
            reply = QMessageBox.warning(
                self,
                "脚本配置不合法",
                f"以下脚本配置不合法，运行时会被跳过：\n{details}\n\n是否仍然运行？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return False
        reply = QMessageBox.question(
            self,
            "确认运行",
            f"即将运行 {len(enabled_keys)} 个脚本，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _run_chain(self, config_data: dict, enabled_keys: set[str], label: str) -> None:
        """生成并运行脚本链（真实 ChainService；ui_state 用内存副本选择，不持久化）。

        周常开关（enabled）是纯内存 UI 态，不参与配置写入；周常是否执行由
        chain_gen 按 ui_state 持久化的 weekly_start（周几起）判断，运行链时
        写入脚本配置（与日常副本选择落盘模型一致）。

        直接 Popen 新控制台窗口运行 runner（cmd 可见链日志）：
        - runner 用 python.exe（pythonw 无控制台，输出无处可去）
        - CREATE_NEW_CONSOLE 开独立 cmd 窗口（复用 run_chain_command(block=False)
          会把 stdout/stderr 丢到 DEVNULL，看不到任何信息）
        """
        ui_state = {name: dict(entry) for name, entry in self._dungeon_state.items()}
        chain_path = self.service.generate_chain(
            config_data, enabled_keys, chain_name="today", ui_state=ui_state
        )
        command, cwd, env = build_script_command(["--chain", chain_path])
        command[0] = command[0].replace("pythonw.exe", "python.exe")
        # CREATE_NEW_CONSOLE 开独立 cmd 窗口（Windows 专属）；Linux CI 无此标志
        creationflags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            creationflags=creationflags,
        )
        self._toast(f"{label}：已生成并运行链 ({len(enabled_keys)} 个脚本)")

    def _launch_all(self):
        """启动全部：生成仅含启用（亮着）脚本的链并运行（对齐旧 GUI enabled 语义）。"""
        # games 与 game_icons 一一对应（同一循环构建），长度必然一致
        keys = {
            g["script_name"]
            for g, icon in zip(self.games, self.game_icons, strict=True)
            if icon.is_enabled()
        }
        if not keys:
            self._toast("没有启用的脚本")
            return
        if not self._confirm_run(keys):
            return
        config_data = self.service.load_config()
        self._run_chain(config_data, keys, "启动全部")

    def _launch_script(self):
        """启动当前选中脚本（直接运行，不走链；对齐旧 GUI 图标左键语义）。

        - python 脚本：走 runner 的 --script 参数用解释器运行
        - external 脚本：解析 exe 路径后 startfile 启动
        """
        game = self._current_game()
        script = game["script_data"]
        if script.get("script_type") == "python":
            resolved = resolve_script_path(script["script_path"])
            if not resolved or not os.path.isfile(resolved):
                self._toast(f"找不到脚本文件：{script['script_path']}")
                return
            command, cwd, env = build_script_command(["--script", resolved])
            subprocess.Popen(command, cwd=cwd, env=env)
        else:
            # external：容错解析（不走 get_script_path 的 assert，配置损坏时 toast 提示）
            exe_path = script.get("script_path", "")
            resolved = resolve_script_path(exe_path) if exe_path else None
            if not resolved or not os.path.isfile(resolved):
                self._toast(f"找不到脚本：{exe_path}")
                return
            os.startfile(resolved)  # noqa: S606 启动脚本本体
        self._toast(f"已启动 {game['display_name']}")

    def _launch_game(self):
        """启动游戏：读取当前游戏 exe 路径并打开（未适配时提示）。

        异环的 get_game_exe_path 已重写为返回启动器（ok-nte.exe）路径，
        故「启动游戏」打开启动器，与其他游戏统一走本方法、无需特判。
        """
        game = self._current_game()
        exe_path = _get_game_exe_path(game["script_name"])
        if not exe_path:
            self._toast(f"{game['display_name']}：未找到游戏路径")
            return
        os.startfile(exe_path)  # noqa: S606 启动游戏（异环为启动器）
        self._toast(f"正在启动 {game['display_name']}…")

    def _open_url(self, url: str, fallback: str, label: str):
        """打开链接（游戏级 meta 有值用其值，否则用通用占位链接）。"""
        target = url or fallback
        webbrowser.open(target)
        self._toast(f"打开{label}：{target}")

    def _open_home(self):
        """打开当前游戏官方主页（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_homepage(self._current_game()["script_name"]),
            _URL_HOME,
            "主页",
        )

    def _open_bilibili(self):
        """打开当前游戏官方 B 站（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_bilibili(self._current_game()["script_name"]),
            _URL_BILIBILI,
            "B站",
        )

    def _open_github(self):
        """打开当前脚本项目的 GitHub 主页（set_config 声明，空则通用占位）。"""
        self._open_url(
            _get_game_github(self._current_game()["script_name"]),
            _URL_HOME,
            "GitHub",
        )

    def _open_script_folder(self):
        """打开当前脚本所在目录（script_path 父目录，资源管理器）。"""
        game = self._current_game()
        script_path = game["script_data"].get("script_path", "")
        resolved = resolve_script_path(script_path) if script_path else None
        if not resolved:
            self._toast(f"{game['display_name']}：未找到脚本路径")
            return
        folder = os.path.dirname(resolved)
        if not os.path.isdir(folder):
            self._toast(f"{game['display_name']}：脚本目录不存在")
            return
        os.startfile(folder)  # noqa: S606 打开脚本所在目录
        self._toast(f"已打开 {game['display_name']} 脚本目录")

    def _load_wallpapers(self) -> dict:
        """读取 config/wallpaper.json（脚本 → 壁纸路径）；缺失返回空。"""
        path = resolve_script_path("config/wallpaper.json")
        if not os.path.isfile(path):
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _save_wallpapers(self):
        """把 _custom_bg 写回 config/wallpaper.json。"""
        path = resolve_script_path("config/wallpaper.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._custom_bg, f, ensure_ascii=False, indent=2)

    def _open_wallpaper(self):
        """更改当前脚本壁纸并持久化。

        选图 → 记录原路径到 _custom_bg → 写 config/wallpaper.json。
        取消选择（空路径）无操作。
        """
        game = self._current_game()
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"选择 {game['display_name']} 壁纸",
            "",
            "图片/视频 (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.webm *.mkv *.mov)",
        )
        if not path:
            return
        self._custom_bg[game["script_name"]] = path
        self._save_wallpapers()
        self._apply_current_game()
        self._toast(f"已更换 {game['display_name']} 壁纸")

    def _open_config_dialog(self):
        """打开当前脚本的配置弹窗（复用 SingleScriptConfigDialog）。

        保存成功（Accept）→ ChainService.update_script 落盘并重载左侧栏；
        删除确认（delete_requested 信号）→ ChainService.remove_script 落盘并重载。
        弹窗删除路径走 close()（非 Accepted），不会误入保存分支。
        """
        game = self._current_game()
        dialog = SingleScriptConfigDialog(
            game["script_name"],
            game["display_name"],
            game["script_data"].get("script_path", ""),
            self,
            script_service=self.service._script_service,
        )
        dialog.delete_requested.connect(self._on_delete_script)
        if dialog.exec() == QDialog.Accepted:
            assert dialog.pending_changes is not None, (
                "[main_window] 配置弹窗 accept 但 pending_changes 为空"
            )
            changes = dialog.pending_changes
            self.service.update_script(
                changes["old_script_name"],
                changes["new_display_name"],
                changes["config_patch"],
                changes["weekly_timeouts"],
            )
            self._reload_games()
            self._toast(f"已保存 {changes['new_display_name']} 配置")

    def _on_delete_script(self, script_name: str):
        """配置弹窗确认删除：先落盘（config.yml + weekly 清理）再重建左侧栏。

        落盘先于 UI 重建，避免 remove_script 断言失败时界面与磁盘状态不一致。
        """
        self.service.remove_script(script_name)
        self._reload_games()
        self._toast("已删除脚本")

    def _reload_games(self):
        """配置保存后重载左侧栏：重读 config.yml 并完整重建 rail（脚本数可变）。"""
        self.games = self._load_games()
        if not self.games:
            # 删光所有脚本：索引置 -1 并清空 rail，避免越界崩溃
            self._current_index = -1
            self._rebuild_left_rail()
            return
        self._current_index = min(self._current_index, len(self.games) - 1)
        self._rebuild_left_rail()
        self._apply_current_game()

    def _toast(self, text: str):
        """右下角 toast 浮层：显示 3 秒后自动消失（frameless 无标题栏提示）。"""
        self.toast_lbl.setText(text)
        self.toast_lbl.adjustSize()
        w, h = self.toast_lbl.width(), self.toast_lbl.height()
        # 底部居中，避开任务卡（左）和启动脚本按钮（右）
        self.toast_lbl.move((CANVAS_W - w) // 2, CANVAS_H - h - 16)
        self.toast_lbl.show()
        self.toast_lbl.raise_()
        self._toast_timer.start(3000)

    def closeEvent(self, event):
        """窗口关闭：停止视频背景层（停止解码），再交给父类。"""
        if self._video_backdrop is not None:
            self._video_backdrop.stop()
        super().closeEvent(event)


def main():
    app = QApplication([])
    # 全局默认字体：QLabel 的 QSS 只设 font-size 未设 font-family，中文字符会 fallback
    # 到宋体(SimSun)；显式设置应用默认字体为微软雅黑后 QSS 文字统一用它
    app.setFont(QFont(FONT_FAMILY))
    # 对齐旧 GUI：config 与模板不一致时弹窗确认（含 30s 限时，超时自动按拒绝处理；
    # CLI/测试不注入）
    ScriptConfig.confirm_before_save = confirm_config_update
    win = LauncherWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
