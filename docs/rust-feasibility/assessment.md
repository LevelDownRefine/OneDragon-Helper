# Rust GUI 完整包评估

2026-09-28，基于 `main@1573bfc` 的迁移 PR 栈。Windows GUI 已接通现有功能，
助手业务保留无 Qt Python CLI，Runner 仍是独立子模块。开发入口为根目录
[`launcher-rust.bat`](../../launcher-rust.bat)，`--demo` 使用隔离的生成配置；
发布构建入口为 [`deploy/build-rust.bat`](../../deploy/build-rust.bat)。

## 完整包结果

比较同一工作树、锁定依赖、同一 Python 环境构建的完整 Qt/Rust 包，两边使用完全相同的
Runner/Updater 二进制。Rust 使用最终 Windows Direct3D 12 + FXC 后端，含独立 CLI、
Python 运行时、发布资源和原生 CRT；没有把单个 Rust EXE 当成完整包。

| 指标 | Qt | Rust | 变化 |
| --- | ---: | ---: | ---: |
| 解压后的程序文件总量 | 145.54 MiB | 68.03 MiB | 减少 53.26% |
| ZIP | 71.79 MiB | 41.92 MiB | 减少 41.60% |
| 程序文件数 | 262 | 128 | 减少 134 |
| 首张任务画面回读，中位数 | 1617.68 ms | 1298.89 ms | 减少 318.79 ms / 19.71% |
| 同一指标的最小～最大值 | 1480.28～1941.09 ms | 1183.62～1499.65 ms | 各 15 次 |

1 MiB = 1,048,576 字节。目录总量是文件字节数之和，不是磁盘分配空间；不含用户配置、
缓存、外部游戏脚本、系统字体和系统图形/媒体组件。体积明细、分组与哈希是本机评估产物，
保存在 `.cache/assessment-size.json`；逐次时间由 `tools/measure_gui_startup.py` 生成，
保存到 `.cache/gui-startup.json`。原始数据均不纳入版本控制，仓库保留结论、测量条件和复现步骤。
CI 使用另一 Python 分发与构建时间，其体积和哈希可能不同。

主要体积收益来自去掉 Qt/PySide6/Shiboken（本机原包约 89.19 MiB），同时新增 Rust
主 EXE 与独立 CLI。原生主程序本身约 11.57 MiB；保留的 Python 运行时、业务依赖、
Runner 和 Updater 仍占较大部分。Rust 不会消除业务初始化和读取外部配置的成本。
之前 OpenGL 原型的体积和启动数字已被本表替代：它在只提供 OpenGL 1.1 的 Windows
环境不能启动，不能作为最终发布方案的性能结论。

## 测量条件与边界

- Windows 11 26200，AMD Ryzen 9 8945HX；本机有 Radeon 610M 与 RTX 5070 Ti Laptop GPU。
  两个前端按自身默认方式选卡：Qt D3D11，Rust wgpu 30.0.1 / Direct3D 12 / FXC。
  这是该机器默认启动行为的对比，没有强制两种框架使用同一适配器。
- Python 3.12.10 conda-forge，`uv.lock` 锁定依赖；Rust 1.97.1，eframe 0.36.2，
  release + capture，`opt-level=s`、thin LTO、单 codegen unit、strip；未使用 UPX。
- 每个前端先预热一次不计入统计，再交替运行 15 次；每次都是新进程。使用暖 OS 缓存，
  不代表重启机器后的冷启动、首次安装或所有配置规模。
- 测量完整发布目录的临时副本；同样的鸣潮/崩铁生成配置、系统字体、可见窗口、
  `--after-update` 跳过自动启动。清除 Python 环境，PATH 仅留 System32；不执行假脚本。
  两边临时副本均用 `RunAsInvoker`，所以时间不包含用户处理 UAC 的等待。
- 起点在创建主进程前；终点是第一张带任务卡的画面完成 GPU 回读，尚未编码 PNG。
  Qt 在首个 `onFrameSwapped` 后 `grabToImage` 回调记录，Rust 使用 egui Screenshot 事件，
  两边统一每 5 ms 观察日志。Rust 仅在测量模式取消截图诊断原有的 250 ms 等待。
- 两种框架的回读机制不同。该指标包含窗口初始化、Python 业务加载与画面生成，
  不是显示器实际呈现时间，也不是一条通用的“所有启动都会快 19.71%”承诺。
  原始 JSON 的 `task_data_ms` 只是辅助诊断：Qt 进入事件循环与 Rust 收到任务响应的
  定义不同，不用它计算启动加速。

## GUI 覆盖与职责

| 现有功能 | Rust GUI | Python CLI / 现有模块 |
| --- | --- | --- |
| 窗口、工具栏、任务卡 | 布局、菜单、中文字体、拖动/最小化/关闭 | 声明解析、日常/周常读写与反读 |
| 脚本管理与配置 | 增删确认、排序、勾选、配置表单、任务开关 | 身份/路径校验、保存、显式初始化 |
| 导航、图标、拖入 | 系统关联打开、Windows 图标、原生文件拖入 | 资源位置、快捷方式与目标解析 |
| 单脚本/游戏/批量启动 | 确认、运行选项、启动控制 | 命令生成、现有 Runner、失败重跑、邮件、恢复声音 |
| 自动启动/自动关机 | 启动倒计时、独立关机确认窗 | 启动设置、运行后动作；仅确认码 42 才关机 |
| 每日计划 | 表单、状态及错误回显 | 原任务计划注册、配置保存、无 Qt daily 入口 |
| 备份/恢复 | 路径选择、覆盖确认、进度与结果 | 原服务 ZIP、恢复前备份、本机路径保留 |
| 图片/视频壁纸 | 有界图片解码、Windows Media Foundation 静音播放 | 映射、缩图和首帧缓存保存 |
| 助手更新 | 状态、下载、取消、安装与退出 | 下载校验、包类型隔离、双进程交接、安装和回滚 |
| 原 CLI 与独立分发 | 主 EXE 转发原参数和退出码 | 随包 CLI、Runner/Updater、更新租约和首启模板 |

完整分支和 PR 依赖见[迁移计划](migration-plan.md)，按底部依赖向顶部顺序审阅/合并。
本轮只创建 PR，没有合并或发布 release。原 Qt 入口继续可用，Rust ZIP 与 Qt ZIP 分开。
查询适配器可能仍做模板对齐，保留已有初始化实现和说明，不为此次迁移重写 Config 类。

## 验收与已知限制

本地 Ubuntu 全量 1249 项（1205 通过、44 项 Windows EXE 前置跳过）；Windows Rust
74 项、Ruff、rustfmt、严格 Clippy 通过。完整 Rust 包的 10 项本地 EXE 检查通过，
包含 PE 图标/UAC/CRT 导入、无 Qt 冻结模块、实际 CLI、运行租约和真实窗口绘制。
主窗口与关机确认窗分别验证自动选卡和强制 WARP，截图后正常取消/退出。
截图诊断等待异步回读时继续推进帧提交，避免静止画面在 WARP 下停在未完成的回读；
回归测试同时检查普通界面保持空闲、待截图界面持续推进。
BAT 演示入口也已在强制 WARP 下实际启动、截图检查。

Windows CI 对完整包另跑管理员 EXE 集成测试，包括原 GUI CLI 兼容、Runner、升级、
锁占用/回滚和 GUI/CLI 双进程自然退出后替换。测试使用隔离的假脚本和临时安装，
不触碰真实游戏、用户备份、系统关机或邮件发送。每日计划注册/回滚用模拟 COM 验证，
没有在用户系统注册测试任务；Explorer 到管理员窗口的真实鼠标拖拽仍需手工验收。

Windows 系统提供 FXC、D3D12/WARP；没有附带 DXC 或软件 OpenGL DLL。
Media Foundation 与编解码器来自系统，Windows N 等缺少媒体组件的环境须安装相应组件；
不能承诺任意视频编码均可播放。非 Windows 原生功能有明确限制，不作为本次验收平台。
正常关窗会回收 CLI；强杀/系统故障的进程树托管，以及恢复中断后的整批回滚不在本轮新增范围。
源码模式不能原位更新，正式包只接受相同前端类型的更新。

## 复现

按[发布工具说明](../../tools/README.md)构建两份干净完整包，激活项目 Python 环境后运行：

```powershell
python tools/measure_gui_startup.py --qt-package deploy/dist/OneDragon-Helper --rust-package deploy/dist/rust/OneDragon-Helper --output .cache/gui-startup.json --runs 15
```

工具先验证清单/哈希，只修改临时副本；Rust 直接使用随包的截图诊断，Qt 只在临时 QML
加入画面回读回调。输出环境、主 EXE SHA-256、逐次样本和中位数/范围。
提前退出、缺少任务就绪标记或截图异常退出会使测量失败，不会计作快速启动。
它会反复打开并关闭测试窗口；只在 Windows 运行，不需要管理员权限。

体积按通过清单校验的程序目录统计文件长度，ZIP 使用原发布工具的压缩方式。
本次 Qt 目录为 `deploy/dist/qt-assessment/OneDragon-Helper`；两个包使用同一 Rust 构建
生成的 Runner/Updater，确保公共组件没有构建差异。
