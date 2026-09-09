"""配置操作入口：选择操作后关闭，具体动作由控制器执行。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from src.gui.dialogs import (
    BG_HOVER,
    BG_INPUT,
    BLUE,
    BORDER,
    TEXT,
    TEXT_MUTED,
    FormDialogBase,
    make_font,
)
from src.gui.icons import UiIconProvider


class ConfigDialog(FormDialogBase):
    """配置操作列表；新增入口时在此补充文案，在控制器补充对应动作。"""

    _ACTIONS = (
        ("backup", "备份配置", "保存为 ZIP，便于换机迁移"),
        ("restore", "恢复配置", "从备份恢复，保留本机游戏路径"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
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
        subtitle = QLabel("管理子脚本的配置文件")
        subtitle.setFont(make_font(size=12))
        subtitle.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;"
        )
        layout.addWidget(subtitle)
        layout.addSpacing(4)

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

    def _select_action(self, action: str) -> None:
        """仅返回操作标识，关闭弹窗后由控制器调 service。"""
        self.selected_action = action
        self.accept()
