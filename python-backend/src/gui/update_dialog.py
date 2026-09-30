"""手动更新弹窗；只展示状态并发出操作请求。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from src.gui.dialogs import (
    BG_INPUT,
    BLUE,
    BORDER,
    TEXT,
    TEXT_MUTED,
    FormDialogBase,
    make_font,
    outlined_qss,
    primary_button_qss,
)


class UpdateDialog(FormDialogBase):
    actionRequested = Signal()
    closeRequested = Signal()
    releasesRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("更新 OneDragon-Helper")
        self.setWindowModality(Qt.ApplicationModal)
        self.setFixedWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        title = QLabel("更新 OneDragon-Helper")
        title.setFont(make_font(size=20, bold=True))
        title.setStyleSheet(f"color: {TEXT}; background: transparent;")
        layout.addWidget(title)
        self.version_label = QLabel()
        self.version_label.setTextFormat(Qt.PlainText)
        self.version_label.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;"
        )
        layout.addWidget(self.version_label)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.PlainText)
        self.status_label.setFont(make_font(size=13))
        self.status_label.setStyleSheet(f"color: {TEXT}; background: transparent;")
        layout.addWidget(self.status_label)
        self.previous_label = QLabel()
        self.previous_label.setTextFormat(Qt.PlainText)
        self.previous_label.setWordWrap(True)
        self.previous_label.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;"
        )
        self.previous_label.hide()
        layout.addWidget(self.previous_label)
        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setFixedHeight(160)
        self.notes.setFont(make_font(size=12))
        self.notes.setStyleSheet(
            f"QTextEdit {{ color: {TEXT}; background: {BG_INPUT}; "
            f"border: 1px solid {BORDER}; border-radius: 8px; padding: 10px; }}"
        )
        self.notes.hide()
        layout.addWidget(self.notes)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(22)
        self.progress.setStyleSheet(
            f"QProgressBar {{ color: {TEXT}; background: {BG_INPUT}; "
            f"border: 1px solid {BORDER}; border-radius: 6px; text-align: center; }}"
            f"QProgressBar::chunk {{ background: {BLUE}; border-radius: 5px; }}"
        )
        self.progress.hide()
        layout.addWidget(self.progress)
        self.hint = QLabel("更新仅替换程序文件，保留你的配置、壁纸、日志和备份。")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        layout.addWidget(self.hint)
        footer = QHBoxLayout()
        self.releases_button = QPushButton("发布页面")
        self.close_button = QPushButton("关闭")
        self.action_button = QPushButton("检查更新")
        for button in (self.releases_button, self.close_button, self.action_button):
            button.setAutoDefault(False)
            button.setMinimumHeight(32)
            button.setFont(make_font(size=12))
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(outlined_qss(color=TEXT_MUTED))
        self.action_button.setStyleSheet(primary_button_qss())
        self.action_button.setMinimumWidth(130)
        self.action_button.clicked.connect(self.actionRequested)
        self.close_button.clicked.connect(self.reject)
        self.releases_button.clicked.connect(self.releasesRequested)
        footer.addWidget(self.releases_button)
        footer.addStretch()
        footer.addWidget(self.close_button)
        footer.addWidget(self.action_button)
        layout.addLayout(footer)

    def show_state(self, state: str, message: str) -> None:
        actions = {
            "checking": "正在检查…",
            "available": "下载更新",
            "downloading": "正在下载…",
            "ready": "安装并重启",
            "installing": "正在准备安装…",
            "current": "重新检查",
            "error": "重试",
            "unsupported": "检查更新",
            "cancelling": "正在取消…",
        }
        assert state in actions
        self.status_label.setText(message)
        self.action_button.setText(actions[state])
        self.action_button.setEnabled(
            state in {"available", "ready", "current", "error"}
        )
        self.action_button.setVisible(state != "unsupported")
        self.close_button.setEnabled(state not in {"installing", "cancelling"})
        self.close_button.setText("取消下载" if state == "downloading" else "关闭")
        self.releases_button.setEnabled(state != "installing")
        busy = state in {"checking", "downloading", "installing", "cancelling"}
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0 if busy else 100)
        self.progress.setTextVisible(state == "downloading")
        if state == "downloading":
            self.progress.setFormat("正在连接…")
        self.adjustSize()

    def show_progress(self, received: int, total: int) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(int(received * 100 / total) if total else 0)
        self.progress.setFormat(
            f"{received / 1024**2:.1f} / {total / 1024**2:.1f} MB"
            if received < total
            else "下载完成，正在校验…"
        )

    def reject(self) -> None:
        self.closeRequested.emit()

    def closeEvent(self, event) -> None:
        event.ignore()
        self.reject()
