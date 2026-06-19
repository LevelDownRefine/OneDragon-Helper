import sys
import os
import textwrap
import yaml

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QScrollArea, QAbstractButton
)
from PySide6.QtCore import Qt, QTimer, QEasingCurve, QVariantAnimation
from PySide6.QtGui import QFont, QPainter, QPen, QColor, QPainterPath, QBrush

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "OneDragon-ScriptChainer", "src"))
from one_dragon.utils.os_utils import get_path_under_work_dir
from script_chainer.utils.process_utils import launch_in_terminal
from script_chainer.utils.runner_utils import build_runner_command

TIMEOUT_SECONDS = 60


# ── 数据工具 ──────────────────────────────────────────────────────────────────

def infer_name(entry: dict, index: int) -> str:
    for key in ("display_name", "game_label"):
        v = entry.get(key, "").strip()
        if v:
            return v
    sp = entry.get("script_path", "")
    game = entry.get("game_process_name", "").strip()
    if sp:
        basename = os.path.splitext(os.path.basename(sp))[0]
        return f"{basename}  ·  {game}" if game else basename
    return game or f"Script #{index + 1}"


def infer_subtitle(entry: dict) -> str:
    parts = []
    sp = entry.get("script_path", "")
    if sp:
        parts.append(textwrap.shorten(sp, width=60, placeholder="…"))
    t = entry.get("run_timeout_seconds")
    if t:
        parts.append(f"超时 {t}s")
    return "   ".join(parts)


def load_config(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"[错误] 找不到配置文件: {path}")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"[错误] YAML 解析失败: {e}")
        sys.exit(1)
    if not isinstance(data, dict):
        print("[错误] 配置文件格式不正确，期望顶层为 dict")
        sys.exit(1)
    return data


def save_config(data: dict, path: str):
    try:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    except OSError as e:
        print(f"[错误] 写入配置失败: {e}")
        sys.exit(1)


# ── 自绘钩形复选框 ────────────────────────────────────────────────────────────

class CheckBox(QAbstractButton):
    """
    纯 QPainter 矢量复选框。

    使用 QVariantAnimation 驱动填充动画，避免依赖 PySide6 Q_PROPERTY 注册机制。
    初始化顺序：先完成所有数据成员和动画对象赋值，再连接信号，防止构造期间
    toggled 提前触发。动画对象以 self 为 parent 管理生命周期，self 本身作为
    valueChanged 的响应目标而非 QPropertyAnimation 的 targetObject，避免
    对象同时充当 target 和 parent 引发的销毁顺序问题。
    """

    _C_BG_OFF   = QColor("#1e1e2e")
    _C_BG_ON    = QColor("#89b4fa")
    _C_BORDER   = QColor("#585b70")
    _C_BORDER_H = QColor("#89b4fa")
    _C_CHECK    = QColor("#1e1e2e")
    SIZE = 22

    def __init__(self, parent=None):
        super().__init__(parent)

        self._fill: float = 1.0

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._on_anim_value)

        self.setCheckable(True)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.PointingHandCursor)

        # setChecked 在信号连接前执行，blockSignals 确保不触发 _on_toggle
        self.blockSignals(True)
        self.setChecked(True)
        self.blockSignals(False)

        self.toggled.connect(self._on_toggle)

    def _on_anim_value(self, value: float):
        self._fill = float(value)
        self.update()

    def _on_toggle(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._fill)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        r = self.rect().adjusted(1, 1, -1, -1)
        radius = 5.0
        f = max(0.0, min(1.0, self._fill))

        def lerp(a: int, b: int) -> int:
            return max(0, min(255, int(a + f * (b - a))))

        bg = QColor(
            lerp(self._C_BG_OFF.red(),   self._C_BG_ON.red()),
            lerp(self._C_BG_OFF.green(), self._C_BG_ON.green()),
            lerp(self._C_BG_OFF.blue(),  self._C_BG_ON.blue()),
        )
        p.setBrush(QBrush(bg))
        border_color = self._C_BORDER_H if self.underMouse() else self._C_BORDER
        p.setPen(QPen(border_color, 1.8))
        p.drawRoundedRect(r, radius, radius)

        if f > 0.01:
            p.setOpacity(f)
            p.setPen(QPen(self._C_CHECK, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            x0, y0 = r.x(), r.y()
            w, h = r.width(), r.height()
            path = QPainterPath()
            path.moveTo(x0 + w * 0.18, y0 + h * 0.50)
            path.lineTo(x0 + w * 0.42, y0 + h * 0.72)
            path.lineTo(x0 + w * 0.82, y0 + h * 0.28)
            p.drawPath(path)

        p.end()

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


# ── 脚本卡片 ──────────────────────────────────────────────────────────────────

class ScriptCard(QFrame):
    """
    点击卡片任意区域均可切换复选框。mousePressEvent 通过 childAt() 判断
    点击目标：若命中 CheckBox 本身，则由 CheckBox 自身的事件处理，卡片层
    不重复 toggle，避免两次翻转导致状态抖动。
    """

    def __init__(self, entry: dict, index: int, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("ScriptCard")
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        self.checkbox = CheckBox()
        layout.addWidget(self.checkbox, 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)

        name_lbl = QLabel(infer_name(entry, index))
        name_lbl.setObjectName("CardTitle")
        text_col.addWidget(name_lbl)

        sub = infer_subtitle(entry)
        if sub:
            sub_lbl = QLabel(sub)
            sub_lbl.setObjectName("CardSub")
            sub_lbl.setWordWrap(True)
            sub_lbl.setMaximumWidth(440)
            text_col.addWidget(sub_lbl)

        layout.addLayout(text_col, 1)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            child = self.childAt(event.position().toPoint())
            if child is not self.checkbox:
                self.checkbox.toggle()
        super().mousePressEvent(event)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_checked(self, v: bool):
        self.checkbox.setChecked(v)


# ── 样式表 ────────────────────────────────────────────────────────────────────

STYLE = """
QWidget#Root {
    background: #1e1e2e;
}
QLabel#MainTitle {
    color: #cdd6f4;
    font-size: 16px;
    font-weight: bold;
}
QLabel#CountdownLabel {
    color: #f38ba8;
    font-size: 12px;
}
QFrame#ScriptCard {
    background: #313244;
    border-radius: 10px;
}
QFrame#ScriptCard:hover {
    background: #45475a;
}
QLabel#CardTitle {
    color: #cdd6f4;
    font-size: 13px;
    font-weight: 600;
}
QLabel#CardSub {
    color: #6c7086;
    font-size: 11px;
}
QPushButton#BtnSelectAll, QPushButton#BtnDeselectAll {
    background: #45475a;
    color: #cdd6f4;
    border: none;
    border-radius: 7px;
    padding: 6px 18px;
    font-size: 12px;
}
QPushButton#BtnSelectAll:hover, QPushButton#BtnDeselectAll:hover {
    background: #585b70;
}
QPushButton#BtnConfirm {
    background: #a6e3a1;
    color: #1e1e2e;
    border: none;
    border-radius: 8px;
    padding: 9px 28px;
    font-size: 13px;
    font-weight: bold;
}
QPushButton#BtnConfirm:hover {
    background: #94e2d5;
}
QPushButton#BtnCancel {
    background: #313244;
    color: #f38ba8;
    border: 1.5px solid #f38ba8;
    border-radius: 8px;
    padding: 9px 22px;
    font-size: 13px;
}
QPushButton#BtnCancel:hover {
    background: #45475a;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: #1e1e2e;
    width: 6px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #585b70;
    border-radius: 3px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
"""


# ── 主窗口 ────────────────────────────────────────────────────────────────────

class SelectorWindow(QWidget):
    """
    closeEvent 统一负责停止倒计时，覆盖所有关闭路径（确认、取消、点 X）。
    windowFlags 去掉最大化/最小化按钮，防止固定布局在拉伸后变形。
    """

    def __init__(self, script_list: list):
        super().__init__()
        self.script_list = script_list
        self.selected_result = None

        self.setObjectName("Root")
        self.setWindowTitle("脚本启动器")
        self.setMinimumWidth(540)
        self.setStyleSheet(STYLE)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 20, 24, 20)
        root_layout.setSpacing(14)

        # ── 标题行 ──
        title_row = QHBoxLayout()
        title = QLabel("选择本次要运行的脚本")
        title.setObjectName("MainTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        self.countdown_lbl = QLabel(f"⏱  {TIMEOUT_SECONDS}s 后自动全选运行")
        self.countdown_lbl.setObjectName("CountdownLabel")
        title_row.addWidget(self.countdown_lbl)
        root_layout.addLayout(title_row)

        # ── 分割线 ──
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #313244;")
        root_layout.addWidget(line)

        # ── 滚动区域 ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        card_layout = QVBoxLayout(scroll_widget)
        card_layout.setSpacing(8)
        card_layout.setContentsMargins(0, 0, 0, 0)

        self.cards: list[ScriptCard] = []
        for i, entry in enumerate(script_list):
            card = ScriptCard(entry, i)
            self.cards.append(card)
            card_layout.addWidget(card)

        card_layout.addStretch()
        scroll.setWidget(scroll_widget)
        scroll.setFixedHeight(min(len(script_list) * 74 + 12, 420))
        root_layout.addWidget(scroll)

        # ── 全选 / 全不选 ──
        sel_row = QHBoxLayout()
        sel_row.setSpacing(8)
        btn_all = QPushButton("全选")
        btn_all.setObjectName("BtnSelectAll")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none = QPushButton("全不选")
        btn_none.setObjectName("BtnDeselectAll")
        btn_none.clicked.connect(lambda: self._set_all(False))
        sel_row.addWidget(btn_all)
        sel_row.addWidget(btn_none)
        sel_row.addStretch()
        root_layout.addLayout(sel_row)

        # ── 确认 / 取消 ──
        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.addStretch()
        btn_cancel = QPushButton("取消（不运行）")
        btn_cancel.setObjectName("BtnCancel")
        btn_cancel.clicked.connect(self._on_cancel)
        btn_confirm = QPushButton("✔  确认运行选中项")
        btn_confirm.setObjectName("BtnConfirm")
        btn_confirm.clicked.connect(self._on_confirm)
        action_row.addWidget(btn_cancel)
        action_row.addWidget(btn_confirm)
        root_layout.addLayout(action_row)

        # ── 倒计时 ──
        self._remaining = TIMEOUT_SECONDS
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.adjustSize()
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width()  - self.width())  // 2,
            (screen.height() - self.height()) // 2,
        )

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)

    def _tick(self):
        self._remaining -= 1
        self.countdown_lbl.setText(f"⏱  {self._remaining}s 后自动全选运行")
        if self._remaining <= 0:
            print("[超时] 已自动全选运行所有脚本。")
            self.selected_result = list(self.script_list)
            self.close()

    def _on_confirm(self):
        self.selected_result = [
            entry for entry, card in zip(self.script_list, self.cards)
            if card.is_checked()
        ]
        self.close()

    def _on_cancel(self):
        self.selected_result = None
        self.close()

    def _set_all(self, checked: bool):
        for card in self.cards:
            card.set_checked(checked)


# ── 入口 ─────────────────────────────────────────────────────────────────────

def update_config(input_path: str, output_path: str):
    config = load_config(input_path)
    script_list = config.get("script_list", [])

    if not script_list:
        print("配置文件中没有找到 script_list，退出。")
        sys.exit(1)

    app = QApplication(sys.argv)

    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", "sans-serif"])
    font.setPointSize(10)
    app.setFont(font)

    win = SelectorWindow(script_list)
    win.show()
    app.exec()

    selected = win.selected_result
    if selected is None:
        print("用户取消，未输出任何配置。")
        sys.exit(0)

    save_config({"script_list": selected}, output_path)
    print(f"已输出 {len(selected)} 个脚本配置到: {output_path}")


if __name__ == "__main__":
    chain_name = "99.yml"
    dir_path = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(dir_path, "config.yml")
    output_path = get_path_under_work_dir("config", "script_chain", chain_name)
    update_config(input_path, output_path)

    cmd, cwd = build_runner_command(chain_name)
    launch_in_terminal(
        command=cmd,
        cwd=cwd,
        title=f'运行脚本链 {chain_name}',
    )
