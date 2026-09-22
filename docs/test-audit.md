# 测试审查记录

## 2026-09-21：合并与整理

基线：`5531ebb`。本轮检查主仓 66 个源码测试文件及发现入口；调整测试与文档，生产代码、runner 指针及 golden JSON 基线未改动。

| 发现 | 整理与补强 |
|---|---|
| 图标测试分散在 `test_gui_widgets.py` 与 `test_icons.py` | 合并到 `test_icons.py`；分别验证来源、提取缓存、默认回退与编码 |
| `test_set_config.py` 混放底层 I/O、字典更新和周常边界 | I/O 移至 `test_utils_sub_config.py`，字典更新归入 `test_utils_dict.py`，周常边界并入 `test_weekly.py`，Daily 读失败语义归入 `test_daily.py` |
| 基类、公开分发和游戏路径接口混在子类测试中 | 移回 `test_set_config.py`，子类文件保留脚本特性与模板对齐 |
| 未选择任务、未知脚本、日常更新、模板对齐、周常布尔开关、静音开关有同形用例 | 合并为具名参数场景；保留各输入及预期，补齐保存调用和无关字段保护 |
| 自身图标测试只断言非空；缓存测试只验证字典有键 | 验证返回对象身份、默认图标未调用、第二次提取命中缓存，以及空图标和异常后的重试 |
| 静音异常测试没有调用或日志断言 | 同时验证调用参数、错误日志和异常类型，确保故障有记录且不打断链 |
| 6 个 GUI 文件从 `test_qml_launcher` 借用夹具，脚本字典浅拷贝 | 提取 `gui_helpers.py`，按需创建应用并深拷贝条目；补不同桥接实例互不污染的回归 |
| 配置弹窗测试替换 Qt 基类，冷导入发生元类冲突 | 仅替换业务弹窗，使用真实 `QDialog` 返回枚举 |
| 反读测试替换 `safe_update`，终末地种子因此漏掉必需开关 | 移除字段更新替身，使用合法原生配置，走真实写入与反读 |
| 资源读取测试依赖其它文件预热 NTE 单例 | 显式构造被测适配器并临时替换注册项，验证后续读取不重新初始化 |
| golden 冷运行时构造期对齐改变种子，整套运行却因缓存命中通过 | 独立注册表、隔离构造期原生 I/O，再装入固定种子；重复构建验证一致性和注册表恢复，原 JSON 基线保持不变 |

### 验证

- 整理前 Ubuntu 全量：1124 条，27 条打包测试按原有前置条件跳过。
- 四类进程内故障注入均触发目标断言：误用默认图标、禁用缓存、静音步骤不执行、日常漏保存；均无导入错误替代目标失败。
- 整理后 Ubuntu 全量及逐用例倒序：均为 1090 条，1063 条源码测试通过，27 条打包测试按原有前置条件跳过。
- 66 个源码测试文件逐文件独立进程运行全部通过；运行后未生成真实 `config.yml`、`schedule.yml` 或 `weekly.yml`。
- `ruff check src tests tools`、`ruff format --check src tests tools`（含原版本 runner 源码）及 `git diff --check` 均通过。

## 2026-09-22：按职责分目录

源码测试归入 `gui`、`config`、`service`、`utils`、`log`、`tools`；跨模块辅助代码归入 `support`。CLI、launcher、link 与 `src` 顶层对应，保留在测试根目录；静态夹具、golden 基线与 Windows 打包测试保留各自目录。

- 为子目录添加测试包入口，CI 与文档统一使用 `discover -s tests -t .`，避免测试包遮蔽业务同名模块。
- 更新 GUI 共享夹具、差异比较与进程模拟的导入，以及配置夹具路径；同步脚本测试改为直接从项目 `tools` 包导入，移除搜索路径修改。
- 同步脚本测试结束后恢复命令行参数和配置路径，临时文件由测试清理机制回收。
- 迁移前后逐文件对比测试类与方法名，保持 66 个源码文件、1063 个测试方法及全部原有场景。

验证：Ubuntu 全量与倒序均为 1090 条（1063 条通过，27 条 Windows 打包测试按原有条件跳过）；66 个源码文件独立运行通过。各子目录分别发现的用例集合与全量一致，无重复或遗漏；同步脚本测试连续运行两遍后恢复原全局状态。Ruff 检查、格式检查及差异检查均通过，未生成真实用户配置。

## 当前文件清单

方法数不展开 `subTest`；用例合并后的数量下降不代表删除对应场景。`tests/gui/helpers.py`、`tests/support/` 和 fixtures 为辅助资源；`sim_schedule_win.py` 是人工全链路模拟入口。runner 仅列清单，本轮未改动，测试由其独立 CI 执行。

### 源码

66 个文件，1063 个测试方法。

| 文件 | 方法数 | 主要范围 |
|---|---:|---|
| [config/test_arknights_config_safety.py](../tests/config/test_arknights_config_safety.py) | 19 | MAA 原生配置的编辑、初始化和持久化边界。 |
| [config/test_bgi_readback.py](../tests/config/test_bgi_readback.py) | 4 | BGI 一条龙旧格式与用户编辑后的任务表兼容性。 |
| [config/test_daily.py](../tests/config/test_daily.py) | 32 | Daily（声明规则层）：声明解析出的落点、读写规则、特殊日常的覆写点。 |
| [config/test_daily_config.py](../tests/config/test_daily_config.py) | 14 | 新声明接入原有单副本菜单；资源 I/O 用 mock 隔离。 |
| [config/test_daily_sources.py](../tests/config/test_daily_sources.py) | 28 | 日常持有资源读取规则；周常复用通用键路径读取。 |
| [config/test_endfield_config_safety.py](../tests/config/test_endfield_config_safety.py) | 4 | 终末地（ok-ef / 粥）config 安全性测试。 |
| [config/test_game_config_roundtrip.py](../tests/config/test_game_config_roundtrip.py) | 3 | 游戏 config 往返保真测试（以「类似崩铁 M7A」的夹具驱动真实读写路径）。 |
| [config/test_generate_config.py](../tests/config/test_generate_config.py) | 6 | 测试 src/config/generate_config.py：首启生成与损坏兜底。 |
| [config/test_golden_daily.py](../tests/config/test_golden_daily.py) | 2 | 固定种子 → 全菜单选择 → 落盘差异和反读；只替换文件 I/O 与外部资源。 |
| [config/test_maa_activity.py](../tests/config/test_maa_activity.py) | 10 | MAA 活动缓存和声明菜单的契约测试，不访问真实安装目录。 |
| [config/test_set_config.py](../tests/config/test_set_config.py) | 37 | ScriptConfig 注册表、共享实例、公开分发接口和游戏路径适配。 |
| [config/test_set_config_readback.py](../tests/config/test_set_config_readback.py) | 19 | 反读测试：get_daily_readback / get_weekly_task 读回 set_* 写入的值。 |
| [config/test_set_config_subclasses.py](../tests/config/test_set_config_subclasses.py) | 54 | 测试 set_config.py 中各 ScriptConfig 子类的行为。 |
| [config/test_task_config.py](../tests/config/test_task_config.py) | 12 | 日常和周常共用声明规则，不引入运行期多日常接口。 |
| [config/test_task_declarations.py](../tests/config/test_task_declarations.py) | 7 | 声明中的字段、物理名、别名接入原有子类读写流程。 |
| [config/test_weekly.py](../tests/config/test_weekly.py) | 38 | 周常落点（``src.config.weekly``）：声明校验、装配、支持查询与各周常的落点读写。 |
| [gui/test_background.py](../tests/gui/test_background.py) | 19 | 测试 src/gui/controllers/background.py：自定义壁纸缓存与背景解析。 |
| [gui/test_config_dialog.py](../tests/gui/test_config_dialog.py) | 6 | 配置弹窗：点选操作后关闭，取消不选择操作。 |
| [gui/test_config_warmer.py](../tests/gui/test_config_warmer.py) | 3 | 测试 ConfigWarmer：启动后空闲逐脚本预热，失败不中断、全部完成发 finished。 |
| [gui/test_daily_plan_dialog.py](../tests/gui/test_daily_plan_dialog.py) | 6 | 每日计划：真实表单保存、取消、错误保留与暂停恢复。 |
| [gui/test_game_list_controller.py](../tests/gui/test_game_list_controller.py) | 9 | 模块行为回归 |
| [gui/test_game_list_model.py](../tests/gui/test_game_list_model.py) | 7 | 测试 GameListModel（QML ListView 的 QAbstractListModel）。 |
| [gui/test_gui_backup.py](../tests/gui/test_gui_backup.py) | 15 | 测试 src/gui/controllers/backup.py：一键备份 / 恢复的 GUI 动作。 |
| [gui/test_gui_control_bubble.py](../tests/gui/test_gui_control_bubble.py) | 1 | 控制模式气泡：真实 QML 点击、批量启停与退出操作。 |
| [gui/test_gui_dialogs.py](../tests/gui/test_gui_dialogs.py) | 23 | 测试 src/gui/dialogs.py：SingleScriptConfigDialog。 |
| [gui/test_gui_file_drop.py](../tests/gui/test_gui_file_drop.py) | 11 | Windows 拖放桥：撤销 OLE、整窗接收与句柄释放，无桌面依赖。 |
| [gui/test_gui_game_hint.py](../tests/gui/test_gui_game_hint.py) | 1 | 启动游戏悬停提示：显示图标、缺失回退与切换刷新。 |
| [gui/test_gui_layout.py](../tests/gui/test_gui_layout.py) | 1 | 布局参数改动须同时作用于窗口裁切、菜单边界和点击区域。 |
| [gui/test_gui_links.py](../tests/gui/test_gui_links.py) | 8 | 测试 src/gui/controllers/links.py：LinksController 各跳转动作。 |
| [gui/test_gui_script_drop.py](../tests/gui/test_gui_script_drop.py) | 14 | 外部脚本拖入窗口：URL / 快捷方式解析、添加与拖放动作。 |
| [gui/test_gui_shutdown_dialog.py](../tests/gui/test_gui_shutdown_dialog.py) | 9 | 测试 src/gui/shutdown_dialog.py：关机确认窗与 Qt 失败降级。 |
| [gui/test_gui_startup_dialog.py](../tests/gui/test_gui_startup_dialog.py) | 14 | 测试 src/gui/startup_dialog.py：启动确认窗与 Qt 失败降级。 |
| [gui/test_gui_task_card.py](../tests/gui/test_gui_task_card.py) | 25 | 测试 src/gui/controllers/task_card.py：多周常 items 与选副本持久化。 |
| [gui/test_gui_window.py](../tests/gui/test_gui_window.py) | 1 | 测试 src/gui/controllers/window.py：悬浮条窗口控制的判空守卫。 |
| [gui/test_icons.py](../tests/gui/test_icons.py) | 15 | 脚本图标：来源选择、默认回退、提取缓存和 PNG 编码。 |
| [gui/test_launch_controller.py](../tests/gui/test_launch_controller.py) | 9 | 测试 src/gui/controllers/launch.py：LaunchController 手动运行流程。 |
| [gui/test_qml_bridge_taskcard.py](../tests/gui/test_qml_bridge_taskcard.py) | 13 | 测试 QmlBridge 任务卡后端（日常副本 / 周常周几）。 |
| [gui/test_qml_launcher.py](../tests/gui/test_qml_launcher.py) | 36 | 测试 src.gui.main_window 与 QML 应用骨架：脚本列表、背景切换、视频回退。 |
| [gui/test_run_confirm_dialog.py](../tests/gui/test_run_confirm_dialog.py) | 15 | 测试 src/gui/run_confirm_dialog.RunConfirmDialog：「启动全部」确认弹窗。 |
| [gui/test_video_wallpaper.py](../tests/gui/test_video_wallpaper.py) | 7 | 视频首帧缓存与实际 QML 占位切换。 |
| [log/test_log_monitor.py](../tests/log/test_log_monitor.py) | 65 | 测试日志解析器 |
| [log/test_notify_mail.py](../tests/log/test_notify_mail.py) | 16 | 测试 src/log/notify_mail.py：send_mail 默认关闭、smtplib 发送与 keyring 取密。 |
| [service/test_backup_service.py](../tests/service/test_backup_service.py) | 24 | 普通 ZIP 配置迁移：真实临时文件覆盖字节往返、换机定位与失败边界。 |
| [service/test_chain_gen.py](../tests/service/test_chain_gen.py) | 13 | 测试 src/service/chain_gen.py：_resolve_daily_run 的覆盖规则（自 weekly_timeouts.py 迁入）。 |
| [service/test_chain_service.py](../tests/service/test_chain_service.py) | 24 | 测试 src/service/chain_service.py：无头测试，全部 mock 被包装函数。 |
| [service/test_daily_plan.py](../tests/service/test_daily_plan.py) | 36 | 每日计划：配置往返、系统任务注册与每次触发时读取最新配置。 |
| [service/test_run_actions.py](../tests/service/test_run_actions.py) | 1 | 测试 src/service/run_actions.py：各 post_run/pre_run step 动作。 |
| [service/test_schedule.py](../tests/service/test_schedule.py) | 38 | 测试 src/service/schedule.py：定时运行的 pre_run / core / post_run 流水线。 |
| [service/test_startup_options.py](../tests/service/test_startup_options.py) | 4 | 自动启动设置：旧配置兼容、非法输入与实际 YAML 往返。 |
| [support/test_config_diff.py](../tests/support/test_config_diff.py) | 4 | 配置差异断言必须区分类型变化、缺键与真实的占位字符串。 |
| [test_cli.py](../tests/test_cli.py) | 41 | 源码级 CLI 单测（offscreen，CI / 普通终端均可真跑）。 |
| [test_launcher.py](../tests/test_launcher.py) | 4 | 测试 src/launcher.py：首次初始化流程 |
| [test_link.py](../tests/test_link.py) | 6 | 测试 src.link 的链接分发与降级逻辑。 |
| [tools/test_sync_oknte_tasks.py](../tests/tools/test_sync_oknte_tasks.py) | 6 | tools/sync_oknte_tasks.py 离线回归测试（不联网，monkeypatch 抓取）。 |
| [tools/test_sync_okww.py](../tests/tools/test_sync_okww.py) | 7 | sync_okww_tasks 的单测：聚焦最前插入模型的重排逻辑（不触网）。 |
| [utils/test_utils.py](../tests/utils/test_utils.py) | 15 | 模块行为回归 |
| [utils/test_utils_config.py](../tests/utils/test_utils_config.py) | 25 | 测试 src/utils_config.py：config.yml 读写与单脚本条目查询（模块函数）。 |
| [utils/test_utils_dict.py](../tests/utils/test_utils_dict.py) | 5 | 字典字段更新：变更、幂等、缺键与类型约束。 |
| [utils/test_utils_mute.py](../tests/utils/test_utils_mute.py) | 5 | 测试 src/utils_mute.py：运行中系统静音执行（config 读写见 test_utils_runner）。 |
| [utils/test_utils_runner.py](../tests/utils/test_utils_runner.py) | 59 | 测试 src/utils_runner.py：脚本配置合法性校验与命令构造/运行。 |
| [utils/test_utils_shortcut.py](../tests/utils/test_utils_shortcut.py) | 6 | 快捷方式读取：保留完整启动信息，COM 错误可恢复且不写回。 |
| [utils/test_utils_shutdown.py](../tests/utils/test_utils_shutdown.py) | 5 | 测试 src/utils_shutdown.py：关机命令编排与确认分支（纯逻辑，不加载 Qt）。 |
| [utils/test_utils_sub_config.py](../tests/utils/test_utils_sub_config.py) | 39 | 脚本标识、路径解析、默认条目和原生配置 I/O。 |
| [utils/test_utils_wallpaper.py](../tests/utils/test_utils_wallpaper.py) | 15 | 测试 src/utils/utils_wallpaper.py：壁纸表读写的损坏兜底与原子写。 |
| [utils/test_utils_weekly.py](../tests/utils/test_utils_weekly.py) | 32 | 测试 src/utils_weekly.py：周常起始日与每周超时的读写与迁移。 |
| [utils/test_yaml_roundtrip.py](../tests/utils/test_yaml_roundtrip.py) | 11 | YAML 往返读写回归测试。 |

### Windows 打包

6 个文件，27 个测试方法。

| 文件 | 方法数 | 主要范围 |
|---|---:|---|
| [test_close_running_exe.py](../tests/exe/test_close_running_exe.py) | 3 | 针对打包产物 OneDragon-Helper.exe 的「运行前关闭残留进程」集成测试（模拟真实情景）。 |
| [test_gui_exe.py](../tests/exe/test_gui_exe.py) | 8 | 针对打包产物 OneDragon-Helper.exe 的集成测试（专门测 GUI exe）。 |
| [test_gui_rendering_exe.py](../tests/exe/test_gui_rendering_exe.py) | 1 | 真实打包界面在默认 D3D11 与 WARP 下的绘制验证。 |
| [test_image_formats_exe.py](../tests/exe/test_image_formats_exe.py) | 2 | 打包产物的 Qt 图片插件防回归测试。 |
| [test_runner_exe.py](../tests/exe/test_runner_exe.py) | 2 | 针对打包产物 OneDragon-Helper-Runner.exe 的集成测试（专门测 exe）。 |
| [test_schedule_exe.py](../tests/exe/test_schedule_exe.py) | 11 | 针对打包产物的 schedule 集成测试（真实 exe + 真实子进程 + 假脚本/假游戏）。 |

### runner 子模块

4 个文件，45 个测试方法。

| 文件 | 方法数 | 主要范围 |
|---|---:|---|
| [test_game_launch.py](../src/runner/tests/test_game_launch.py) | 8 | 测试「运行脚本前启动游戏」（ScriptConfig.game_path）。 |
| [test_launcher.py](../src/runner/tests/test_launcher.py) | 15 | 测试运行器入口 launcher：参数解析 + run_chain 主流程跑通（不启动任何外部进程）。 |
| [test_script_chain_resilience.py](../src/runner/tests/test_script_chain_resilience.py) | 18 | 测试脚本链全阻塞模式下的容错行为。 |
| [test_script_config.py](../src/runner/tests/test_script_config.py) | 4 | 测试脚本链配置中 script_path 的相对路径解析。 |

## 2026-09-19：历史审查

审查基线：`c4d4347`（2026-09-19）。范围包括主仓源码测试、Windows 打包测试、runner 子模块测试、测试夹具与 CI 发现入口。

### 发现与修复

| 问题 | 影响 | 修复 |
|---|---|---|
| golden 测试文件为空，JSON 基线无人消费 | 日常菜单、保存落点与反读整体回归漏检 | 恢复固定种子及逐选项快照；更新基线必须显式传 `--update` |
| 异环损坏 routine 测试使用不存在的「每日任务」名称 | 捕获了分发错误，目标校验失效也能通过 | 逐个检查两个真实日常的 `read_enabled`，断言具体错误及读盘调用 |
| 4 个文件的 `unittest.main()` 位于最后一个测试类之前 | 直接执行模块会漏掉 17 条测试 | 统一移至文件末尾 |
| CLI 及打包图片模块初始化真实配置 | 依赖本机安装状态，可能写用户配置或残留输出 | CLI 每例使用临时模板和输出；图片使用固定 JPEG/WebP 夹具 |
| QML 测试导入时删除用户缓存；跨模块桥接夹具依赖模块级初始化 | 导入有副作用，干净配置下两条桥接测试失败 | 禁用磁盘缓存即可；构造桥接夹具时隔离原生配置读取 |
| 启动器测试把全局 exists 设为 False，却仍初始化真实适配器 | 独立执行时 MAA 模板加载失败，整套运行被缓存掩盖 | 将适配器初始化作为独立协作者打桩并断言调用 |
| 临时目录、YAML 文件、图标缓存、Qt 插件路径及日志状态未完整恢复 | 污染后续用例与本机环境 | 上下文管理器、addCleanup 和状态恢复 |
| 配置 diff 用 Python 宽松相等判断，缺失占位符与真实字符串混用 | True→1、1→1.0 和部分新增/删除字段可能被当成无变化 | 递归比较类型，区分缺失与真实值，补 4 条工具回归测试 |
| runner 的临时目录、等待 mock 和 sys.argv 未完整恢复 | 用例结束后残留资源和全局状态 | 在 [runner PR #1](https://github.com/LevelDownRefine/OneDragonRunner/pull/1) 中独立修复，主仓仅更新指针 |
| runner 禁用脚本测试使用非法配置且没有启动断言 | 跳过非法配置也会通过，无法证明禁用生效 | 使用合法解释器路径，校验配置有效且两个执行入口均未调用 |

### 验证

- 修复前：Ubuntu 全量 1072 条，25 条 Windows 打包测试按前置条件跳过；runner 单独 45 条通过。
- 修复后源码逐模块独立进程：65 个文件、1052 条测试全部通过，运行前后不生成真实 config/schedule/weekly.yml。
- golden：7 个脚本，167 次菜单选择；记录保存文件、字段差异和每步全部日常的反读。种子包含无关字段以检查误改。
- 故障注入：停用 routine 校验、日常写入、CLI 输出时，修复后的测试均失败，且没有导入错误替代目标失败。
- 主仓 Ubuntu 全量、倒序测试及 ruff check/format 的结果记录在 PR 验证说明中；Windows 打包与解码由 build-exe 工作流执行。runner 测试由 OneDragonRunner 仓库自己的 CI 执行，主仓 CI 不重复运行。
