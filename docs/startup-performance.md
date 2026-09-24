# GUI 启动性能实验

基线：`1767da4`；实验分支：`codex/startup-performance`。

## 改动

仅将更新网络库 `requests` 移到检查或下载更新时导入。GUI 启动和本地版本信息读取不需要该网络库，因此避免在主窗口显示前加载它及其依赖。

首次网络导入由原有更新工作线程承担，之后复用 Python 模块缓存。保留更新请求、下载异常处理和清理逻辑；不增加依赖。

新增独立进程测试，确认导入 GUI 入口并创建 AppService 后仍未加载 requests；更新服务测试改为直接 mock `requests.get`。

## 测量

同一 Windows / Python 3.12.10 / PySide6 6.8.0.2 环境，从基线独立构造“仅延迟 requests”的版本。应用 `.pyc` 已生成，预热一轮后随机顺序测量 20 轮，每次使用新进程，取中位数。

| 方案 | GUI 首帧 |
| --- | ---: |
| 基线 | 588.3 ms |
| 仅延迟 requests（最终方案） | 480.2 ms |

本机该场景下缩短约 **108 ms / 18.4%**。逐轮配对的节省中位数为 108.7 ms，95% bootstrap 区间为 101.9～118.3 ms。

计时从应用依赖导入前开始，在 `QQmlApplicationEngine.objectCreated` 时连接 `frameSwapped`，第一次触发即记录并退出。不含进程创建、解释器启动和夹具准备，不是端到端 EXE 启动时间。

实验使用离屏渲染、临时配置和资源副本、空脚本列表、`--after-update`；各轮复用已初始化的临时配置。Qt 在测量钩子中提前导入，该时间计入两个方案且条件一致。不读取个人配置、不运行外部脚本、不删除用户全局 QML 缓存。

结果仅适用于本机源码、文件系统缓存已预热的上述场景，不代表重启电脑后的冷启动、实际脚本配置、显卡渲染或发布 EXE。

## 验证

- Ubuntu 全量：`PYTHONPATH=src python -m unittest discover -s tests -t . -p "test*.py"`，共 1183 项，1150 项通过、33 项 Windows EXE 测试按规则跳过。
- `ruff check src tests tools`、`ruff format --check src tests tools` 通过。
- 更新检查、下载、取消、失败清理及 GUI/CLI 原有行为继续由现有测试覆盖。
- 发布 EXE 功能由本 PR 的 Windows 打包 CI 验证；未测量 EXE 启动性能。
