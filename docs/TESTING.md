# 测试与验证

源码测试在 Ubuntu 运行，Windows CI 验证打包 EXE。新增或修改功能须补测试；共享接口、跨模块修改和重构必须跑全套，不能只跑相关文件。纯文档修改检查链接、命令和实现是否一致。

## 环境

从仓库根目录执行：

```bash
git submodule update --init --recursive
uv sync --frozen
```

然后激活 `.venv`：Linux 用 `source .venv/bin/activate`，Windows Bash 用 `source .venv/Scripts/activate`，CMD 用 `call env.bat`。

`runner/`、`updater/` 必须完整检出。`leveldown-updater` 从本地子模块严格可编辑安装；新增、删除模块，或 Windows 编辑器原子替换文件导致链接失效时，执行 `uv sync --reinstall-package leveldown-updater`。不要用空模块或跳过导入掩盖环境问题。

## Python 检查

两套测试都有名为 `tests` 的包，必须分进程运行：

```bash
python -m unittest discover -s python-backend/tests -t python-backend -p "test*.py"
python -m unittest discover -s python-gui/tests -t python-gui -p "test*.py"
ruff check python-backend python-gui tools runner
ruff format --check python-backend python-gui tools runner
```

格式失败时运行 `ruff format .`，再重新检查。不要通过跳过用例或放宽断言使 CI 通过。

| 位置 | 内容 |
| --- | --- |
| `python-backend/tests/config/` | 配置适配、声明、迁移与 golden |
| `python-backend/tests/service/` | 业务编排与 CLI 契约 |
| `python-backend/tests/exe/` | Windows 打包集成测试 |
| `python-gui/tests/` | 控制器、弹窗、CLI 客户端及 Qt EXE |
| `rust-gui/tests/` | Rust 单元、协议和真实后端集成测试 |

测试使用临时目录和 mock，不读写真实安装、用户配置或系统任务。Qt 用例通过共享 `get_app()` 创建应用并在 offscreen 下运行。清理使用上下文管理器或 `addCleanup`，缓存和单例也需隔离。夹具不要命名为 `test_*.py`。

断言具体行为与结果；同一契约的多组数据可用 `subTest`，独立迁移另设测试文件。避免只断言非空、复制实现或依赖执行顺序。

## Golden 更新

日常读写基线保存在 `python-backend/tests/golden/daily_baseline.json`。正常测试只读基线；行为确实变更后显式更新并审查差异：

```bash
uv run --directory python-backend python -m tests.config.test_golden_daily --update
```

## Rust 检查

```bash
cargo fmt --manifest-path rust-gui/Cargo.toml --check
cargo clippy --manifest-path rust-gui/Cargo.toml --locked --all-features --all-targets -- -D warnings
cargo test --manifest-path rust-gui/Cargo.toml --locked --all-features
```

真实后端集成测试需要完整 Python 环境，可将 `ODH_TEST_PYTHON` 指向已安装工作区依赖的解释器。Windows CI 额外覆盖 D3D12/WARP、视频解码、进程及系统接口；Linux 结果不能替代这些验证。

## Windows 打包验证

在管理员终端、已激活环境中执行：

```powershell
.deploy\build.bat
python tools/build_rust.py --test
```

前者构建 Qt 包并测试，后者构建 Rust 完整包并测试。真实 EXE 用例在临时副本中运行；UAC 前置不满足时可能阻塞，不要直接在日常安装目录测试。CLI 单独验证可通过 `ODH_CLI_EXE` 指定已打包路径，执行 `test_headless_exe.py`。

构建、资源清单及输出位置见 [工具指南](../tools/README.md)。需手动模拟计划运行时使用 `uv run --directory python-backend python -m tests.sim_schedule_win`；它会弹出交互窗口。

## CI

- `ci.yml`：Ubuntu Python 测试、ruff 与 Rust 检查。
- `build-exe.yml`：Windows Qt 包、独立 CLI、Rust 完整包的构建与真实 EXE 验证。
- `release.yml`：tag 发布复用同提交的成功构建，无法复用时重建并测试。

发布目录在测试前后校验，禁止混入配置、日志或测试产物。日志位置见 [日志说明](../python-backend/src/log/README.md)。
