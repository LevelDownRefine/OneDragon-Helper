"""启动设置与配置迁移入口；关闭后由控制器保存设置并执行所选操作。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.gui.dialogs import (
    BG_HOVER,
    BG_INPUT,
    BLUE,
    BORDER,
    TEXT,
    TEXT_MUTED,
    FormDialogBase,
    make_font,
    spin_box_qss,
)
from src.gui.icons import UiIconProvider
from src.service.schedule import MAX_STARTUP_DELAY_SECONDS, StartupOptions


class ConfigDialog(FormDialogBase):
    """配置操作列表；新增入口时在此补充文案，在控制器补充对应动作。"""

    _ACTIONS = (
        ("backup", "备份配置", "保存为 ZIP，便于换机迁移"),
        ("restore", "恢复配置", "从备份恢复，保留本机游戏路径"),
    )

    def __init__(self, parent=None, *, startup_options: StartupOptions | None = None):
        super().__init__(parent)
        if startup_options is None:
            startup_options = StartupOptions()
        self.selected_action: str | None = None
        self.setWindowTitle("配置")
        self.setFixedWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        title = QLabel("配置")
        title.setFont(make_font(size=20, bold=True))
        title.setStyleSheet(f"color: {TEXT}; background: transparent; border: none;")
        layout.addWidget(title)
        subtitle = QLabel("自动启动与配置迁移")
        subtitle.setFont(make_font(size=12))
        subtitle.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;"
        )
        layout.addWidget(subtitle)
        layout.addSpacing(4)

        startup = QFrame(self)
        startup.setObjectName("startupSettings")
        startup.setStyleSheet(
            f"QFrame#startupSettings {{ background: rgba(29, 43, 64, 160); "
            f"border: 1px solid {BORDER}; border-radius: 10px; }}"
        )
        startup_layout = QVBoxLayout(startup)
        startup_layout.setContentsMargins(16, 14, 16, 14)
        startup_layout.setSpacing(12)
        self.startup_cb = self._make_checkbox("打开后自动启动全部脚本")
        self.startup_cb.setFont(make_font(size=13, bold=True))
        self.startup_cb.setChecked(startup_options.enabled)
        startup_layout.addWidget(self.startup_cb)

        countdown_row = QHBoxLayout()
        countdown_row.setSpacing(8)
        self.startup_delay = QSpinBox(self)
        self.startup_delay.setRange(1, MAX_STARTUP_DELAY_SECONDS)
        self.startup_delay.setValue(startup_options.delay_seconds)
        self.startup_delay.setFixedSize(76, 30)
        self.startup_delay.setFont(make_font(size=12))
        self.startup_delay.setAlignment(Qt.AlignCenter)
        self.startup_delay.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.startup_delay.setStyleSheet(spin_box_qss())
        self.startup_delay.setAccessibleName("自动启动倒计时（秒）")
        self.startup_delay.setToolTip("1–3600 秒")
        self.startup_delay.setEnabled(startup_options.enabled)
        self.startup_cb.toggled.connect(self.startup_delay.setEnabled)
        for content in ("在", self.startup_delay, "秒后按上次配置启动"):
            if isinstance(content, str):
                label = QLabel(content)
                label.setFont(make_font(size=12))
                label.setStyleSheet(
                    f"color: {TEXT_MUTED}; background: transparent; border: none;"
                )
                countdown_row.addWidget(label)
            else:
                countdown_row.addWidget(content)
        countdown_row.addStretch()
        startup_layout.addLayout(countdown_row)
        layout.addWidget(startup)

        icons = UiIconProvider()
        for action, label, description in self._ACTIONS:
            button = QPushButton(self)
            button.setObjectName(f"{action}Action")
            button.setAccessibleName(label)
            button.setAutoDefault(False)
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumHeight(78)
            button.setStyleSheet(f"""
                QPushButton {{ background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 10px; }}
                QPushButton:hover {{ background: {BG_HOVER}; border-color: {BLUE}; }}
                QPushButton:focus {{ border-color: {BLUE}; }}
            """)
            row = QHBoxLayout(button)
            row.setContentsMargins(16, 12, 16, 12)
            row.setSpacing(14)
            icon = QLabel()
            icon.setPixmap(
                icons.requestPixmap(action, None, None).scaled(
                    30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
            icon.setFixedSize(36, 36)
            icon.setAlignment(Qt.AlignCenter)
            icon.setAttribute(Qt.WA_TransparentForMouseEvents)
            icon.setStyleSheet("background: transparent; border: none;")
            row.addWidget(icon)
            text = QVBoxLayout()
            text.setSpacing(5)
            for content, size, color, bold in (
                (label, 14, TEXT, True),
                (description, 11, TEXT_MUTED, False),
            ):
                line = QLabel(content)
                line.setFont(make_font(size=size, bold=bold))
                line.setAttribute(Qt.WA_TransparentForMouseEvents)
                line.setStyleSheet(
                    f"color: {color}; background: transparent; border: none;"
                )
                text.addWidget(line)
            row.addLayout(text, 1)
            button.clicked.connect(
                lambda _checked=False, chosen=action: self._select_action(chosen)
            )
            layout.addWidget(button)

        footer = QHBoxLayout()
        save_hint = QLabel("关闭时保存，下次打开生效")
        save_hint.setFont(make_font(size=11))
        save_hint.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        footer.addWidget(save_hint)
        footer.addStretch()
        close = QPushButton("关闭")
        close.setObjectName("closeConfig")
        close.setAutoDefault(False)
        close.setFixedSize(80, 30)
        close.setFont(make_font(size=12))
        close.setStyleSheet(self._SECONDARY_BTN_STYLE)
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        layout.addSpacing(4)
        layout.addLayout(footer)

    @property
    def startup_options(self) -> StartupOptions:
        """返回最终表单值；关闭或 Esc 时也提交尚未失焦的数字输入。"""
        self.startup_delay.interpretText()
        return StartupOptions(self.startup_cb.isChecked(), self.startup_delay.value())

    def _select_action(self, action: str) -> None:
        """仅返回操作标识，关闭弹窗后由控制器调 service。"""
        self.selected_action = action
        self.accept()
