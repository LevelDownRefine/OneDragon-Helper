# 测试审查记录

审查基线：`c4d4347`（2026-09-19）。范围包括主仓源码测试、Windows 打包测试、runner 子模块测试、测试夹具与 CI 发现入口。

## 发现与修复

| 问题 | 影响 | 修复 |
|---|---|---|
| golden 测试文件为空，JSON 基线无人消费 | 日常菜单、保存落点与反读整体回归漏检 | 恢复固定种子及逐选项快照；更新基线必须显式传 `--update` |
| 异环损坏 routine 测试使用不存在的「每日任务」名称 | 捕获了分发错误，目标校验失效也能通过 | 逐个检查两个真实日常的 `read_enabled`，断言具体错误及读盘调用 |
| 4 个文件的 `unittest.main()` 位于最后一个测试类之前 | 直接执行模块会漏掉 17 条测试 | 统一移至文件末尾 |
| CLI 及打包图片模块初始化真实配置 | 依赖本机安装状态，可能写用户配置或残留输出 | CLI 每例使用临时模板和输出；图片使用固定 JPEG/WebP 夹具 |
| QML 测试导入时删除用户缓存；跨模块桥接夹具依赖模块级初始化 | 导入有副作用，干净配置下两条桥接测试失败 | 禁用磁盘缓存即可；构造桥接夹具时隔离原生配置读取 |
| 启动器测试把全局 exists 设为 False，却仍初始化真实适配器 | 独立执行时 MAA 模板加载失败，整套运行被缓存掩盖 | 将适配器初始化作为独立协作者打桩并断言调用 |
| 临时目录、YAML 文件、图标缓存、Qt 插件路径及日志状态未完整恢复 | 污染后续用例与本机环境 | 上下文管理器、addCleanup 和状态恢复 |
| 主仓 discovery 不包含 runner/tests | 主仓升级子模块时其 45 条测试未被 CI 执行 | CI 增加独立 runner 测试步骤 |
| 配置 diff 用 Python 宽松相等判断，缺失占位符与真实字符串混用 | True→1、1→1.0 和部分新增/删除字段可能被当成无变化 | 递归比较类型，区分缺失与真实值，补 4 条工具回归测试 |

## 验证

- 修复前：Ubuntu 全量 1072 条，25 条 Windows 打包测试按前置条件跳过；runner 单独 45 条通过。
- 修复后源码逐模块独立进程：65 个文件、1052 条测试全部通过，运行前后不生成真实 config/schedule/weekly.yml。
- golden：7 个脚本，167 次菜单选择；记录保存文件、字段差异和每步全部日常的反读。种子包含无关字段以检查误改。
- 故障注入：停用 routine 校验、日常写入、CLI 输出时，修复后的测试均失败，且没有导入错误替代目标失败。
- Ubuntu 最终全量、倒序测试、runner、ruff check/format 的结果记录在 PR 验证说明中；Windows 打包与解码由 build-exe 工作流执行。

## 文件清单

下表按测试方法统计，不展开 subTest。源码 65 个文件，打包 6 个文件，runner 4 个文件。`tests/sim_schedule_win.py` 是人工全链路模拟入口，不纳入 unittest 发现；`config_diff.py`、`process_sim.py` 和 fixtures 为辅助资源。

### 源码

| 文件 | 测试数 | 主要范围 |
|---|---:|---|
| [test_arknights_config_safety.py](../tests/test_arknights_config_safety.py) | 19 | MAA 原生配置的编辑、初始化和持久化边界 |
| [test_background.py](../tests/test_background.py) | 19 | 测试 src/gui/controllers/background.py：自定义壁纸缓存与背景解析 |
| [test_backup_service.py](../tests/test_backup_service.py) | 24 | 普通 ZIP 配置迁移：真实临时文件覆盖字节往返、换机定位与失败边界 |
| [test_bgi.py](../tests/test_bgi.py) | 4 | test_bgi |
| [test_chain_gen.py](../tests/test_chain_gen.py) | 11 | 测试 src/service/chain_gen.py：_resolve_daily_run 的覆盖规则（自 weekly_timeouts.py 迁入） |
| [test_chain_service.py](../tests/test_chain_service.py) | 24 | 测试 src/service/chain_service.py：无头测试，全部 mock 被包装函数 |
| [test_cli.py](../tests/test_cli.py) | 41 | 源码级 CLI 单测（offscreen，CI / 普通终端均可真跑） |
| [test_config_dialog.py](../tests/test_config_dialog.py) | 6 | 配置弹窗：点选操作后关闭，取消不选择操作 |
| [test_config_diff.py](../tests/test_config_diff.py) | 4 | 配置差异断言必须区分类型变化、缺键与真实的占位字符串 |
| [test_daily.py](../tests/test_daily.py) | 29 | Daily（声明规则层）：声明解析出的落点、读写规则、特殊日常的覆写点 |
| [test_daily_config.py](../tests/test_daily_config.py) | 14 | 新声明接入原有单副本菜单；资源 I/O 用 mock 隔离 |
| [test_daily_plan.py](../tests/test_daily_plan.py) | 29 | 每日计划：配置往返、系统任务注册与每次触发时读取最新配置 |
| [test_daily_plan_dialog.py](../tests/test_daily_plan_dialog.py) | 6 | 每日计划：真实表单保存、取消、错误保留与暂停恢复 |
| [test_daily_sources.py](../tests/test_daily_sources.py) | 28 | 日常持有资源读取规则；周常复用通用键路径读取 |
| [test_endfield_config_safety.py](../tests/test_endfield_config_safety.py) | 4 | 终末地（ok-ef / 粥）config 安全性测试 |
| [test_game_config_roundtrip.py](../tests/test_game_config_roundtrip.py) | 3 | 游戏 config 往返保真测试（以「类似崩铁 M7A」的夹具驱动真实读写路径） |
| [test_game_list_controller.py](../tests/test_game_list_controller.py) | 8 | 周几起随 update_script 统一落盘：游戏侧 OSError 属部分失败，提示不回滚 |
| [test_game_list_model.py](../tests/test_game_list_model.py) | 7 | 测试 GameListModel（QML ListView 的 QAbstractListModel） |
| [test_generate_config.py](../tests/test_generate_config.py) | 6 | 测试 src/config/generate_config.py：首启生成与损坏兜底 |
| [test_golden_daily.py](../tests/test_golden_daily.py) | 1 | 固定种子 → 全菜单选择 → 落盘差异和反读；只替换文件 I/O 与外部资源 |
| [test_gui_backup.py](../tests/test_gui_backup.py) | 15 | 测试 src/gui/controllers/backup.py：一键备份 / 恢复的 GUI 动作 |
| [test_gui_control_bubble.py](../tests/test_gui_control_bubble.py) | 1 | 控制模式气泡：真实 QML 点击、批量启停与退出操作 |
| [test_gui_dialogs.py](../tests/test_gui_dialogs.py) | 27 | 测试 src/gui/dialogs.py：SingleScriptConfigDialog |
| [test_gui_file_drop.py](../tests/test_gui_file_drop.py) | 11 | Windows 拖放桥：撤销 OLE、整窗接收与句柄释放，无桌面依赖 |
| [test_gui_game_hint.py](../tests/test_gui_game_hint.py) | 1 | 启动游戏悬停提示：显示图标、缺失回退与切换刷新 |
| [test_gui_layout.py](../tests/test_gui_layout.py) | 1 | 布局参数改动须同时作用于窗口裁切、菜单边界和点击区域 |
| [test_gui_links.py](../tests/test_gui_links.py) | 8 | 测试 src/gui/controllers/links.py：LinksController 各跳转动作 |
| [test_gui_script_drop.py](../tests/test_gui_script_drop.py) | 14 | 外部脚本拖入窗口：URL / 快捷方式解析、添加与拖放动作 |
| [test_gui_shutdown_dialog.py](../tests/test_gui_shutdown_dialog.py) | 9 | 测试 src/gui/shutdown_dialog.py：关机确认窗与 Qt 失败降级 |
| [test_gui_startup_dialog.py](../tests/test_gui_startup_dialog.py) | 14 | 测试 src/gui/startup_dialog.py：启动确认窗与 Qt 失败降级 |
| [test_gui_task_card.py](../tests/test_gui_task_card.py) | 20 | 测试 src/gui/controllers/task_card.py：多周常 items 与选副本持久化 |
| [test_gui_widgets.py](../tests/test_gui_widgets.py) | 9 | 测试 src/gui/icons.py：get_script_icon / get_icon_source 的图标源选择 |
| [test_gui_window.py](../tests/test_gui_window.py) | 2 | 测试 src/gui/controllers/window.py：悬浮条窗口控制的判空守卫 |
| [test_icons.py](../tests/test_icons.py) | 3 | 替代真实 QIcon，仅满足 _exe_icon 的非空判定，避免无头环境依赖平台图标提供器 |
| [test_launch_controller.py](../tests/test_launch_controller.py) | 9 | 测试 src/gui/controllers/launch.py：LaunchController 手动运行流程 |
| [test_launcher.py](../tests/test_launcher.py) | 3 | 测试 src/launcher.py：首次初始化流程 |
| [test_link.py](../tests/test_link.py) | 6 | 测试 src.link 的链接分发与降级逻辑 |
| [test_log_monitor.py](../tests/test_log_monitor.py) | 65 | 测试日志解析器 |
| [test_maa_activity.py](../tests/test_maa_activity.py) | 9 | MAA 活动缓存和声明菜单的契约测试，不访问真实安装目录 |
| [test_notify_mail.py](../tests/test_notify_mail.py) | 16 | 测试 src/log/notify_mail.py：send_mail 默认关闭、smtplib 发送与 keyring 取密 |
| [test_qml_bridge_taskcard.py](../tests/test_qml_bridge_taskcard.py) | 10 | 测试 QmlBridge 任务卡后端（日常副本 / 周常周几） |
| [test_qml_launcher.py](../tests/test_qml_launcher.py) | 34 | 测试 src.gui.main_window 与 QML 应用骨架：脚本列表、背景切换、视频回退 |
| [test_run_actions.py](../tests/test_run_actions.py) | 1 | 测试 src/service/run_actions.py：各 post_run/pre_run step 动作 |
| [test_run_confirm_dialog.py](../tests/test_run_confirm_dialog.py) | 15 | 测试 src/gui/run_confirm_dialog.RunConfirmDialog：「启动全部」确认弹窗 |
| [test_schedule.py](../tests/test_schedule.py) | 38 | 测试 src/service/schedule.py：定时运行的 pre_run / core / post_run 流水线 |
| [test_script_enabled.py](../tests/test_script_enabled.py) | 5 | 持久化脚本勾选：重启/重排按脚本身份回显，保存失败不更改界面 |
| [test_set_config.py](../tests/test_set_config.py) | 38 | 测试 set_config.py 中的子脚本 config 读写基础设施 |
| [test_set_config_readback.py](../tests/test_set_config_readback.py) | 22 | 反读测试：get_daily_readback / get_weekly_task 读回 set_* 写入的值 |
| [test_set_config_subclasses.py](../tests/test_set_config_subclasses.py) | 127 | 测试 set_config.py 中各 ScriptConfig 子类的行为 |
| [test_startup_options.py](../tests/test_startup_options.py) | 4 | 自动启动设置：旧配置兼容、非法输入与实际 YAML 往返 |
| [test_sync_oknte_tasks.py](../tests/test_sync_oknte_tasks.py) | 6 | tools/sync_oknte_tasks.py 离线回归测试（不联网，monkeypatch 抓取） |
| [test_sync_okww.py](../tests/test_sync_okww.py) | 7 | sync_okww_tasks 的单测：聚焦最前插入模型的重排逻辑（不触网） |
| [test_task_config.py](../tests/test_task_config.py) | 12 | 日常和周常共用声明规则，不引入运行期多日常接口 |
| [test_task_declarations.py](../tests/test_task_declarations.py) | 7 | 声明中的字段、物理名、别名接入原有子类读写流程 |
| [test_utils.py](../tests/test_utils.py) | 16 | 验证 PyInstaller 冻结模式下 get_root_dir() 返回 exe 所在目录，而非 __file__ 推导路径 |
| [test_utils_config.py](../tests/test_utils_config.py) | 26 | 测试 src/utils_config.py：config.yml 读写与单脚本条目查询（模块函数） |
| [test_utils_mute.py](../tests/test_utils_mute.py) | 11 | 测试 src/utils_mute.py：运行中系统静音执行（config 读写见 test_utils_runner） |
| [test_utils_runner.py](../tests/test_utils_runner.py) | 56 | 测试 src/utils_runner.py：脚本配置合法性校验与命令构造/运行 |
| [test_utils_shortcut.py](../tests/test_utils_shortcut.py) | 6 | 快捷方式读取：保留完整启动信息，COM 错误可恢复且不写回 |
| [test_utils_shutdown.py](../tests/test_utils_shutdown.py) | 5 | 测试 src/utils_shutdown.py：关机命令编排与确认分支（纯逻辑，不加载 Qt） |
| [test_utils_sub_config.py](../tests/test_utils_sub_config.py) | 22 | 测试 src/utils_sub_config.py：脚本唯一标识、路径解析、脚本路径读取、默认条目构造 |
| [test_utils_wallpaper.py](../tests/test_utils_wallpaper.py) | 15 | 测试 src/utils/utils_wallpaper.py：壁纸表读写的损坏兜底与原子写 |
| [test_utils_weekly.py](../tests/test_utils_weekly.py) | 26 | 测试 src/utils_weekly.py：周常起始日与每周超时的读写与迁移 |
| [test_video_wallpaper.py](../tests/test_video_wallpaper.py) | 7 | 视频首帧缓存与实际 QML 占位切换 |
| [test_yaml_roundtrip.py](../tests/test_yaml_roundtrip.py) | 6 | YAML 往返读写回归测试 |

### Windows 打包

| 文件 | 测试数 | 主要范围 |
|---|---:|---|
| [test_close_running_exe.py](../tests/exe/test_close_running_exe.py) | 3 | 针对打包产物 OneDragon-Helper.exe 的「运行前关闭残留进程」集成测试（模拟真实情景） |
| [test_gui_exe.py](../tests/exe/test_gui_exe.py) | 8 | 针对打包产物 OneDragon-Helper.exe 的集成测试（专门测 GUI exe） |
| [test_gui_rendering_exe.py](../tests/exe/test_gui_rendering_exe.py) | 1 | 真实打包界面在默认 D3D11 与 WARP 下的绘制验证 |
| [test_image_formats_exe.py](../tests/exe/test_image_formats_exe.py) | 2 | 打包产物的 Qt 图片插件防回归测试 |
| [test_runner_exe.py](../tests/exe/test_runner_exe.py) | 2 | 针对打包产物 OneDragon-Helper-Runner.exe 的集成测试（专门测 exe） |
| [test_schedule_exe.py](../tests/exe/test_schedule_exe.py) | 9 | 针对打包产物的 schedule 全链路集成测试（真实 exe + 真实子进程 + 假脚本/假游戏） |

### runner 子模块

| 文件 | 测试数 | 主要范围 |
|---|---:|---|
| [test_game_launch.py](../src/runner/tests/test_game_launch.py) | 8 | 测试「运行脚本前启动游戏」（ScriptConfig.game_path） |
| [test_launcher.py](../src/runner/tests/test_launcher.py) | 15 | 测试运行器入口 launcher：参数解析 + run_chain 主流程跑通（不启动任何外部进程） |
| [test_script_chain_resilience.py](../src/runner/tests/test_script_chain_resilience.py) | 18 | 测试脚本链全阻塞模式下的容错行为 |
| [test_script_config.py](../src/runner/tests/test_script_config.py) | 4 | 测试脚本链配置中 script_path 的相对路径解析 |
