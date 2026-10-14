# Rust GUI 完整包测量

历史样本：2026-09-28，基于 `main@1573bfc` 的迁移 PR 栈。下列数字只代表该次构建和机器；当前功能与限制见 [Rust GUI](../../rust-gui/README.md)。

## 结果

同一工作树、锁定依赖和 Python 环境构建两份完整包，共用相同 Runner/Updater 二进制。Rust 包包含 GUI、无 Qt CLI、Python 运行时、资源与 CRT。

| 指标 | Qt | Rust | 变化 |
| --- | ---: | ---: | ---: |
| 程序文件总量 | 145.54 MiB | 68.03 MiB | −53.26% |
| ZIP | 71.79 MiB | 41.92 MiB | −41.60% |
| 文件数 | 262 | 128 | −134 |
| 首张任务画面回读中位数 | 1617.68 ms | 1298.89 ms | −318.79 ms / −19.71% |
| 最小～最大值 | 1480.28～1941.09 ms | 1183.62～1499.65 ms | 各 15 次 |

体积按文件长度求和（1 MiB = 1,048,576 字节），不含用户数据、外部脚本及系统组件。主要收益来自移除 Qt/PySide6/Shiboken；Python 业务和外部配置初始化仍有成本。

原始数据保存在本机 `.cache/assessment-size.json`、`.cache/gui-startup.json`，未纳入版本控制；CI 的 Python 分发和构建时间不同，体积及哈希可能不同。

## 条件与限制

- Windows 11 26200，Ryzen 9 8945HX，Radeon 610M / RTX 5070 Ti Laptop GPU；两端默认选卡，未强制同一适配器。Qt 用 D3D11，Rust 用 wgpu 30.0.1 / D3D12 / FXC。
- Python 3.12.10 conda-forge，Rust 1.97.1，eframe 0.36.2；Rust release + capture、opt-level=s、thin LTO、单 codegen unit、strip，无 UPX。
- 各预热一次，再交替运行 15 次新进程。测量暖 OS 缓存，不代表冷启动或首次安装。
- 使用临时完整包、相同鸣潮/崩铁生成配置和系统字体；清除 Python 环境，PATH 仅留 System32。`--after-update` 跳过自动运行，`RunAsInvoker` 排除 UAC 等待。
- 起点为创建主进程前，终点为首张任务画面 GPU 回读完成、PNG 编码前。Qt 使用 `onFrameSwapped/grabToImage`，Rust 使用 egui Screenshot；均每 5 ms 观察日志，Rust 测量模式取消截图的 250 ms 等待。
- 两端回读机制不同，结果不是显示器实际呈现时间，也不能推及所有配置。`task_data_ms` 定义不同，不用于计算加速比例。

## 复现

按 [工具指南](../../tools/README.md) 构建干净的完整包，在已激活的 Python 环境中运行：

```powershell
python tools/measure_gui_startup.py --qt-package deploy/dist/OneDragon-Helper --rust-package deploy/dist/rust/OneDragon-Helper --output .cache/gui-startup.json --runs 15
```

工具校验清单后仅修改临时副本，反复打开并关闭可见窗口；需要 Windows，无需管理员。输出环境、EXE 哈希、逐次样本及统计；提前退出、缺少就绪标记或截图失败均使测量失败。

本次 Qt 输出位于 `deploy/dist/qt-assessment/OneDragon-Helper`，公共 Runner/Updater 来自同一次 Rust 构建。功能回归另按 [测试指南](../TESTING.md) 执行。
