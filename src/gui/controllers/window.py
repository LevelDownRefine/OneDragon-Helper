"""窗口控制控制器：系统原生拖动 / 最小化 / 关闭。

独立 QObject。窗口对象经 Qt 应用实例惰性获取（测试 / CLI 路径不依赖 QtWidgets）。
"""

from PySide6.QtCore import QObject, QRectF, Slot
from PySide6.QtGui import QPainterPath, QRegion, QWindow


class WindowController(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)

    def roundWindow(self, window: QWindow, radius: int):
        """按逻辑像素设置整窗圆角，尺寸变化时同步显示与鼠标命中区域。"""
        assert radius >= 0

        def update_mask():
            path = QPainterPath()
            path.addRoundedRect(
                QRectF(0, 0, window.width(), window.height()), radius, radius
            )
            window.setMask(QRegion(path.toFillPolygon().toPolygon()))

        window.widthChanged.connect(update_mask)
        window.heightChanged.connect(update_mask)
        update_mask()

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
        if app is None:
            return
        win = app.focusWindow()
        if win is not None:
            win.showMinimized()

    @Slot()
    def closeWindow(self):
        app = self._app()
        if app is not None:
            app.quit()

    def _app(self):
        from PySide6.QtWidgets import QApplication

        return QApplication.instance()
