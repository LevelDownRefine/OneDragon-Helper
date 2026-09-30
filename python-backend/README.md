# Python 后端

配置适配、脚本编辑、任务编排、日志汇总、更新和 JSON-RPC stdio 入口。
Rust GUI 通过 `src.headless` 调用业务；后端通过 CLI 调用根目录的 `runner/`。
源码运行直接执行 `python <仓库>/runner/launcher.py --chain <配置路径>`，
由 Python 自动定位 runner 内部包，无需修改 `PYTHONPATH`；发布时调用同目录 Runner EXE。

- `src/`：无 Qt 的 Python 业务、CLI 和更新内核。
- `tests/`：后端测试，以及发布包和共享构建工具的集成测试。
- `pyproject.toml`：后端依赖。根目录 uv workspace 统一管理 `.venv/` 和 `uv.lock`。

在仓库根目录运行 `uv sync --frozen` 安装依赖。启动无 GUI 后端：

```sh
uv run --directory python-backend python -m src.headless serve --stdio
```

Python GUI 位于 `python-gui/`，可用根目录 `launcher.bat` 启动。

`config/`、`assets/` 和运行期数据仍以仓库根目录为基准，与调用者当前目录无关。
发布时 Python 模块打入运行库，EXE、用户配置和共享资源的安装位置不变。

测试命令见根目录 [TESTING.md](../TESTING.md)。
