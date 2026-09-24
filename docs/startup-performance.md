# 启动性能实验

基线：`1767da4`；实验分支：`codex/startup-performance`。

## 最终保留

- CLI 分流后才导入 Qt、QML 桥接和拖放模块。除了诊断命令，每日计划与运行链子进程也走这个入口；CLI 可避免整套 GUI 导入，打开主窗口仍需要 Qt。
- 更新网络库 `requests` 在检查或下载更新时导入。本地版本信息和普通启动不需要它；首次网络导入由现有更新工作线程承担，后续复用模块缓存。
- 新进程测试防止 CLI 提前加载 Qt、GUI 提前加载网络库。原有测试的 mock 目标改为实际定义模块。
- 将原日志中的“QML 装载完成（窗口已显示）”更正为“QML 装载完成”，避免把加载完成误当作首帧。

撤回四个控制器的弹窗延迟导入及配套测试改动：单独收益不稳定，合计收益很小。撤回新增阶段日志和首帧监听：它们有诊断用途，本身不提速，本次用外部实验脚本测量。保留原 QML 缓存策略，不更换打包器或增加依赖。

## 单项对照

同一 Windows / Python 3.12.10 / PySide6 6.8.0.2 环境。每个方案从基线独立构造，先生成源码 `.pyc`，预热一轮后随机顺序运行 20 轮，每次使用新进程，下表为中位数。

| 相对基线的改动 | CLI `--version` | GUI 首帧 | 结论 |
| --- | ---: | ---: | --- |
| 无改动 | 366.7 ms | 588.3 ms | 对照 |
| 仅延迟 requests | 253.0 ms | 480.2 ms | GUI 主要收益，保留 |
| 仅 CLI 延迟 Qt | 206.3 ms | 588.0 ms | CLI 有效，GUI 没有测出收益，保留 |
| 仅四处弹窗延迟导入 | 359.0 ms | 579.2 ms | 小收益、波动较大，撤回 |
| **Qt + requests（最终方案）** | **117.3 ms** | **472.7 ms** | CLI 约快 68%，首帧约快 20% |
| 原 PR 全部改动 | 119.6 ms | 466.4 ms | 比最终方案仅再快约 6 ms 的首帧 |

CLI 计时从应用依赖导入前到真实 `launcher.main()` 的 `--version` 退出；首帧在 `QQmlApplicationEngine.objectCreated` 时连接 `frameSwapped`，第一次触发即记录并退出。两者都不含进程创建、解释器启动和夹具准备，不是端到端 EXE 启动耗时。

GUI 使用 `QT_QPA_PLATFORM=offscreen`、临时配置和资源副本、空脚本列表、`--after-update`。各轮复用已初始化的临时配置；不读取个人配置、不运行外部脚本、不删除用户全局 QML 缓存。Qt 在测量钩子中提前导入，但该时间计入所有方案且条件相同；不能据此证明调整 Qt 导入顺序改善真实窗口首帧。

逐轮配对比较，requests 的 GUI 节省中位数为 108.7 ms；Qt 单项为 1.1 ms；弹窗合计为 11.1 ms。后两项的 95% 配对 bootstrap 区间跨过零（Qt：-6.5～13.6 ms；弹窗：-1.5～18.3 ms）。最终方案与原 PR 的首帧差约 5.7 ms，说明撤回小改动仍保留绝大部分收益。

另做过不生成应用 `.pyc` 的 12 轮单项对照：backup、daily_plan、launch、update 四个控制器各自的首帧收益均不稳定，不能把四项都视为独立有效的优化。它们共享 `gui.dialogs` 和 `run_confirm_dialog`，部分延迟导入会被其他路径的提前导入抵消。

这些是文件系统缓存已预热、本机源码、离屏、空列表条件下的结果，不代表重启电脑后的冷启动、实际脚本配置、显卡渲染或发布 EXE。此前首次带 `-X importtime` 的 2.35 秒采样只用于定位热点，不能与普通启动结果混作加速比例。

## 验证

- Ubuntu：`PYTHONPATH=src python -m unittest discover -s tests -t . -p "test*.py"`，共 1183 项，1150 项通过、33 项 Windows EXE 测试按规则跳过。
- `ruff check src tests tools`、`ruff format --check src tests tools` 通过。
- 更新检查、下载、取消和失败清理，以及原有 GUI/CLI 行为测试继续覆盖；新增进程隔离的启动依赖回归测试。
- 原提交 `f231c4d` 的 [Windows 打包 CI](https://github.com/LevelDownRefine/OneDragon-Helper/actions/runs/35944495155) 共 33 项 EXE 测试，31 项通过、2 项跳过。最终修订由后续 CI 重新验证。CI 验证功能，不代表 EXE 启动性能测量。
