"""窗口控制控制器：系统原生拖动 / 最小化 / 关闭。

独立 QObject。窗口对象经 Qt 应用实例惰性获取（测试 / CLI 路径不依赖 QtWidgets）。
"""

from PySide6.QtCore import QObject, Slot


class WindowController(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)

    @Slot()
    def startWindowMove(self):
        """发起系统原生窗口拖动（Windows DWM 接管）。"""
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
