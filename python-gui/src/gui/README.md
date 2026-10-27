# Qt 界面层

只负责 QML、控制器和弹窗；配置读写、适配及业务编排归 [AppService](../../../python-backend/src/service/README.md)。`QmlBridge` 是 QML 唯一门面，组合控制器并通过构造注入协调交互。

## 模块

| 模块 | 职责 |
| --- | --- |
| `main_window.py`、`qml/` | Bridge、主窗口布局和共享主题 |
| `controllers/` | 列表、任务卡、运行、背景、链接、计划、备份和更新 |
| `dialogs.py`、`*_dialog.py` | 表单、确认和结果展示 |
| `cli_client.py` | 持久 CLI 会话、请求编号和异步响应 |
| `icons.py`、`file_drop.py` | 图标与平台拖放 |

主窗口配色集中在 `qml/Theme.js`，原生弹窗色板在 `dialogs.py`。保持纯 QtQuick，不增加控件或效果库依赖。

## CLI 与状态

列表、任务卡、表单、设置、资源、运行、计划、备份和更新统一通过 CLI 会话访问后端，GUI 不导入、构造或持有 AppService。源码使用当前 Python 解释器启动后端，无需独立 CLI EXE；冻结包使用随包 CLI，缺失时按不完整安装包报错，不回退到进程内业务。协议见 [无 Qt CLI](../../../docs/rust-feasibility/headless-cli.md)。

- 使用 QProcess/QTimer 异步收发，禁止 `waitForFinished` / `waitForReadyRead` 阻塞 UI。
- 写入与刷新分别处理。断连使待处理请求失败；重连只重读状态，不重放写入、运行或自动启动。
- 以脚本身份和选择代数丢弃迟到响应，包括 A→B→A。后台任务编号不能跨会话复用。
- 手动勾选仅在内存，重启全选；每日计划对所有脚本生效，使用独立运行选项。
- 弹窗取消不写入，保存失败保留草稿；保存后重读，改名后使用新标识。
- 单脚本配置通过 `ScriptEdit` 提交；附带选项只提交变化字段，布局与规则见 [任务选项](../../../python-backend/src/config/task/task_options.md)。

## 进程与系统交互

拖入 `.exe/.bat/.py/.lnk` 只登记脚本，快捷方式解析和合法性校验归 service。链接及启动目标由后端解析，前端显式调用系统打开或启动。

运行链启动为独立进程，交付参数后关闭 GUI 不终止运行。每日计划启用、演示或更新后启动时跳过窗口自动运行。

更新窗打开时只读本地状态，用户点击检查才联网。备份、恢复、安装期间阻止普通关窗；检查和下载可请求取消，等待任务终态后关闭。更新交接 ready 后退出 GUI，安装与重启归更新器。

## 扩展

新增交互先确定后端接口，再添加控制器及 Bridge property/slot，最后接入 QML 或弹窗。界面只保留展示状态，不创建配置文件或复制业务校验。

从仓库根目录用 `launcher.bat` 启动；验证命令见 [测试指南](../../../docs/TESTING.md)。
