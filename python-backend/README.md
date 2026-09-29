# Python 后端

配置适配、脚本编辑、任务编排、日志汇总、更新和 JSON-RPC stdio 入口。
Rust GUI 通过 `src.headless` 调用业务；后端通过 CLI 调用根目录的 `runner/`。

- `src/`：Python 源码。现有 `src/gui/` 和 Qt 启动入口暂时保留，下轮拆出。
- `tests/`：Python 测试，以及发布包和共享构建工具的集成测试。
- `pyproject.toml`：Python 依赖。根目录 uv workspace 统一管理 `.venv/` 和 `uv.lock`。

在仓库根目录运行 `uv sync --frozen` 安装依赖。启动无 GUI 后端：

```sh
uv run --directory python-backend python -m src.headless serve --stdio
```

现有 Python GUI 可继续用根目录 `launcher.bat`，或：

```sh
uv run --directory python-backend python -m src.launcher
```

`config/`、`assets/` 和运行期数据仍以仓库根目录为基准，与调用者当前目录无关。
发布时 Python 模块打入运行库，EXE、用户配置和共享资源的安装位置不变。

测试命令见根目录 [TESTING.md](../TESTING.md)。
