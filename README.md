# OneDragon-Helper

多游戏自动化脚本调度器：选择脚本与任务，统一配置副本、超时和运行顺序，执行后汇总结果。

![界面示例](assets/demo.png)

- 适配脚本的日常、周常及原生任务开关，也可添加自定义脚本。
- 支持失败重跑、日志分析、邮件汇总、每日计划及完成后关机。
- 提供配置备份恢复、手动更新，以及 Rust、Qt 两套界面。

## 使用

从 [Releases](https://github.com/LevelDownRefine/OneDragon-Helper/releases) 下载并解压完整安装包，运行主程序。Rust 包为 `OneDragon-Helper-Rust.zip`，Qt 包为 `OneDragon-Helper.zip`。各游戏脚本需自行安装，再添加到助手。

## 源码运行

Python 3.11+，依赖由根目录 uv workspace 管理：

```powershell
git submodule update --init --recursive
uv sync --frozen
.launcher-rust.bat
```

Rust 界面另需 Rust 1.95+ 和 Windows MSVC 工具链；Qt 界面使用 `launcher.bat`。启动器读取当前检出的源码，可复用父目录环境。

## 开发导航

| 目录 | 职责 |
| --- | --- |
| [rust-gui](rust-gui/README.md) / [python-gui](python-gui/README.md) | Rust / Qt 界面 |
| [python-backend](python-backend/README.md) | 配置适配、业务服务、无 Qt CLI |
| [runner](runner/README.md) / [updater](updater/README.md) | 运行器 / 更新内核，均为独立子模块 |
| `config/`、`assets/` | 共享声明、模板与资源 |
| [tools](tools/README.md)、`deploy/` | 同步、构建与发布 |

开发前阅读 [项目约束](AGENTS.md)、[编码约定](docs/CONVENTIONS.md) 和 [测试指南](docs/TESTING.md)。
