import subprocess
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ShutdownWindow(QMainWindow):
    def __init__(self, countdown_sec=30):
        super().__init__()
        self.countdown_sec = countdown_sec
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_countdown)

        # 窗口基础设置
        self.setWindowTitle("关机提醒")
        self.setFixedSize(350, 180)
        # 窗口置顶
        self.setWindowFlag(Qt.WindowStaysOnTopHint)

        # 中心组件与布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 倒计时文本标签，字号改为16pt
        self.label_tip = QLabel("")
        self.label_tip.setAlignment(Qt.AlignCenter)
        self.label_tip.setStyleSheet("font-family: 'Microsoft YaHei'; font-size: 16pt; font-weight: 500;")
        main_layout.addWidget(self.label_tip)

        # 按钮行布局
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(20)

        self.btn_shutdown = QPushButton("立即关机")
        self.btn_shutdown.setFixedWidth(100)
        # 按钮字体同步放大
        self.btn_shutdown.setStyleSheet("font-size: 12pt; padding:4px;")
        self.btn_shutdown.clicked.connect(self.do_shutdown)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFixedWidth(100)
        self.btn_cancel.setStyleSheet("font-size: 12pt; padding:4px;")
        self.btn_cancel.clicked.connect(self.close)

        btn_layout.addWidget(self.btn_shutdown)
        btn_layout.addWidget(self.btn_cancel)
        main_layout.addLayout(btn_layout)

        # 启动倒计时计时器
        self.timer.start()
        self.update_countdown()

    def update_countdown(self):
        if self.countdown_sec > 0:
            self.label_tip.setText(f"电脑将在 {self.countdown_sec} 秒后关机\n请保存好您的工作！")
            self.countdown_sec -= 1
        else:
            self.timer.stop()
            self.do_shutdown()

    def do_shutdown(self):
        self.close()
        subprocess.run(
            ["shutdown", "/s", "/t", "0"],
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = ShutdownWindow(countdown_sec=30)
    win.show()
    sys.exit(app.exec())
