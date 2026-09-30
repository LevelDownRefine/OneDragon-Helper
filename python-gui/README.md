# python-gui

OneDragon-Helper 的 PySide6/QML 前端。这里只包含窗口、控制器、弹窗与 GUI
启动入口；配置读写和运行编排统一调用 `python-backend` 的 service。

在仓库根目录同步 workspace 后，可直接启动：

```powershell
uv sync
uv run python -m gui.launcher
```
