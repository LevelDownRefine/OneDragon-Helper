"""独立 QML 进程：点真实菜单，经 CLI 保存整数与布尔选项。"""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
from PySide6.QtTest import QTest

from src.gui.cli_client import CliClient
from src.gui.main_window import QmlBridge
from src.utils.utils_yaml import load_yaml
from tests.gui.helpers import get_app
from tests.support.headless import PROJECT_ROOT, HeadlessFixture


def main():
    app = get_app()

    def wait_for(predicate):
        deadline = time.monotonic() + 12
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(10)
        assert predicate(), "QML/CLI 状态等待超时"

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        fixture = HeadlessFixture(root)
        with root.joinpath("config/config.example.yml").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(
                "- display_name: 崩铁\n  script_path: scripts/March7th-Launcher.exe\n"
            )
        root.joinpath("scripts/March7th-Launcher.exe").touch()
        native = root / "scripts/config.yaml"
        native.write_text(
            "build_target_enable: true\npower_enable: true\n", encoding="utf-8"
        )
        client = CliClient(command=fixture.command("serve", "--stdio"))
        try:
            with (
                patch(
                    "src.gui.controllers.background.BackgroundController.apply_current"
                ),
                patch(
                    "src.gui.controllers.game_list.ScriptIconProvider._load_icon",
                    return_value=QPixmap(1, 1),
                ),
            ):
                bridge = QmlBridge(cli_backend=True, cli_client=client)
                messages = []
                bridge.toastRequested.connect(messages.append)
                qmlRegisterSingletonInstance(
                    QmlBridge, "OneDragonHelper", 1, 0, "Bridge", bridge
                )
                engine = QQmlApplicationEngine()
                engine.addImageProvider("scripticon", bridge.game_list.icon_provider)
                engine.addImageProvider("gameicon", bridge.game_list.game_icon_provider)
                engine.addImageProvider("uiicon", bridge.ui_icon_provider)
                engine.load(
                    QUrl.fromLocalFile(str(PROJECT_ROOT / "src/gui/qml/main.qml"))
                )
                assert len(engine.rootObjects()) == 1
                window = engine.rootObjects()[0]
                window.requestActivate()
                wait_for(lambda: bridge.taskStatus == "已同步")
                QTest.qWait(150)

                def find_item(parent, *, name=None, text=None):
                    pending = [parent]
                    while pending:
                        item = pending.pop()
                        if name is not None and item.objectName() == name:
                            return item
                        if text is not None and item.property("text") == text:
                            return item
                        pending.extend(item.childItems())
                    raise AssertionError(f"未找到 QML 项: {name or text}")

                def click(item):
                    # 二级菜单可能比一级长；先滚动到被测项，不能点击裁剪区外。
                    ancestor = item.parentItem()
                    while ancestor is not None:
                        if ancestor.metaObject().indexOfProperty("contentY") >= 0:
                            point = item.mapToItem(
                                ancestor, QPointF(item.width() / 2, item.height() / 2)
                            )
                            if point.y() > ancestor.height() or point.y() < 0:
                                offset = (
                                    ancestor.property("contentY")
                                    + point.y()
                                    - ancestor.height() / 2
                                )
                                maximum = max(
                                    0,
                                    ancestor.property("contentHeight")
                                    - ancestor.height(),
                                )
                                ancestor.setProperty(
                                    "contentY", max(0, min(offset, maximum))
                                )
                        ancestor = ancestor.parentItem()
                    point = item.mapToScene(
                        QPointF(item.width() / 2, item.height() / 2)
                    )
                    QTest.mouseMove(window, point.toPoint())
                    QTest.qWait(50)
                    point = item.mapToScene(
                        QPointF(item.width() / 2, item.height() / 2)
                    )
                    QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
                    QTest.qWait(50)

                content = window.contentItem()
                click(find_item(content, name="dailyButton"))
                popup = find_item(content, name="dailyPopup")
                assert popup.isVisible()
                click(find_item(popup, text="凝素领域"))
                click(find_item(popup, text="梦州-迅刀"))
                wait_for(lambda: not bridge.taskBusy)
                assert bridge.taskStatus == "已同步", bridge.taskStatus
                state = json.loads(fixture.native.read_text(encoding="utf-8"))
                assert state["Which Forgery Challenge to Farm"] == 1
                assert type(state["Which Forgery Challenge to Farm"]) is int
                bridge.selectGame(2)
                wait_for(lambda: bridge.taskStatus == "已同步")
                click(find_item(content, name="dailyButton"))
                click(find_item(popup, text="每日任务"))
                click(find_item(popup, text="不启用培养目标"))
                wait_for(lambda: not bridge.taskBusy)
                assert bridge.taskStatus == "已同步", bridge.taskStatus
                assert load_yaml(str(native))["build_target_enable"] is False, (
                    messages,
                    popup.isVisible(),
                    popup.property("selName"),
                    bridge.task_card.daily_items,
                )
                assert load_yaml(str(native))["power_enable"] is True
                window.close()
                bridge.close_cli()
        finally:
            client.close()


if __name__ == "__main__":
    main()
