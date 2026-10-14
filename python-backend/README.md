# Python 后端

无 Qt 的业务层：配置适配、脚本链编排、日志分析、计划、备份和更新接入。两套 GUI 经 CLI 共用这些服务，资源路径以项目或安装根目录为基准，不依赖当前工作目录。

| 入口 | 职责 |
| --- | --- |
| [service](src/service/README.md) | AppService 外观及业务编排 |
| [config](src/config/set_config.md) | 外部脚本配置适配 |
| [log](src/log/README.md) | 日志定位与结果分析 |
| [headless](../docs/rust-feasibility/headless-cli.md) | JSON-RPC stdio 协议 |
| `src/update.py` | 独立 updater 子模块的适配、会话及更新器入口 |

从仓库根目录启动 CLI：

```bash
uv run --directory python-backend python -m src.headless serve --stdio
```

依赖声明于 `pyproject.toml`，由根目录 uv workspace 安装；测试见 [测试指南](../docs/TESTING.md)。
