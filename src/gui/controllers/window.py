"""窗口控制控制器：系统原生拖动 / 最小化 / 关闭。

独立 QObject。窗口对象经 Qt 应用实例获取（QGuiApplication / QApplication），
均为惰性 import，避免在非 GUI（测试 / CLI）路径下无谓依赖 QtWidgets。
"""

from PySide6.QtCore import QObject, Slot


class WindowController(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)

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
