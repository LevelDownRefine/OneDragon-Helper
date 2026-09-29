# python-backend/src/service — 服务层（AppService 组合根 + 平级 peer）

把 set_config、runner、链生成与校验内聚为统一薄接口，对 GUI 与 CLI 暴露同一套调用面。
从 python-backend/src/gui/ 分离而出，无 Qt 依赖，故 GUI 与 CLI 共用同一实现，也便于无头测试。

## 设计定位

| 角色 | 说明 |
|------|------|
| 组合根，非协调器 peer | `AppService` 装配各 peer 并薄委托，是 GUI/CLI 唯一入口；各 peer 互不越界 |
| 平级 peer | script_service（脚本管理）/ chain_service（链编排）互不拥有，由组合根装配 |
| 周常运行期参数 | `weekly.yml` 的 `weekly_start` 段（周几起，条目级 `{脚本: {周常: 0 | 1~7}}`，0 = 不启用）与 `weekly_timeouts` 段的读写归 `src.utils.utils_weekly` 模块函数（无状态、无 peer 实例）；周常读写经 `src.config.set_config` 分发给脚本持有的 Weekly，落点归 `src.config.weekly`；schedule.yml 归 schedule 模块函数 |
| 无 Qt 依赖 | 纯业务逻辑，不承载 UI 渲染（关机确认窗归 `python-backend/src/gui/shutdown_dialog.py`） |

## 文件

| 模块 | 职责 |
|------|------|
| app_service.py | 组合根：装配 peer 并薄委托，GUI/CLI 唯一入口 |
| script_service.py | 脚本条目构造、增删改与排序；统一校验并协调助手配置、每周参数及原生任务开关 |
| task_service.py | 脚本列表与任务卡聚合查询；无 GUI 或进程依赖 |
| python-backend/src/link.py | 关联资源、图标与启动目标查询；实际打开和启动归前端 |
| python-backend/src/utils/utils_config.py | config.yml 读写、结构校验、条目查询与配置文件路径解析 |
| python-backend/src/utils/utils_wallpaper.py | 壁纸来源、映射与预览缓存；解码和渲染归前端 |
| python-backend/src/utils/utils_job.py | JobExecutor：单个后台操作的执行、进度、取消与结果保留；不依赖业务模块 |
| python-backend/src/update/service.py | 更新内核与 UpdateSession 会话状态；检查、下载和安装交接共用原实现 |
| chain_service.py | 链编排 peer：链生成、合法性校验、runner 命令构造、调度运行入口 |
| chain_gen.py | 脚本链配置生成：由 enabled_names + 子脚本 config 生成链配置并校验 |
| schedule.py | schedule.yml 读写（StartupOptions 自动启动开关/秒数、RunOptions 运行选项）+ ScheduledRun 调度运行编排 |
| daily_plan.py | 每日计划读写与 Windows 原生任务注册，并可回读任务实际状态；系统仅保存触发时间和 --run-daily 入口 |
| backup_service.py | 配置备份与恢复：普通 ZIP 收集与恢复；按当前脚本目录覆盖，保留游戏路径，未配置脚本跳过 |
| run_actions.py | pre_run / post_run 各 step 的具体动作 |

## 任务卡查询与编辑

任务卡通过 `AppService.app_snapshot/script_view` 查询。查询返回普通字典：日常为 `name/task/sequence/enabled/options`，周常为
`name/task/options/start_day`。保留 JSON 整数与布尔的区别、`0=不启用` 与 `None=未设置`；
读取仍可能触发既有模板对齐，不承诺完全没有写盘副作用。

CLI 编辑入口保留在 `AppService`，直接调用对应的 GUI 原接口：

| 操作 | CLI 入口 | GUI 原入口 |
|------|------|------|
| 选择日常（同时启用） | `select_daily(script_name, daily_name=None, task_name=None, sequence=None)` | `set_script_daily_task` |
| 日常开关 | `enable_daily(script_name, daily_name, enabled)` | `set_script_daily_enabled` |
| 选择周常 | `select_weekly(script_name, weekly_name, task_name)` | `set_script_weekly_task` |
| 周常起始日 | `start_weekly(script_name, weekly_name, start_day)` | `set_weekly_start_for` |

`daily_name` 对应原接口的 `daily_display_name`，参数值原样传入。
四个 CLI 写入口只做 `return self.<原接口>(...)`，返回值及异常原样传递。
原写接口当前返回 `None`，校验与写入由原调用链负责；不增加菜单预读或写后整卡查询。
调用方需要刷新时再调用 `script_view`，并分别处理写入和查询的错误。
周常起始日仍先保存助手侧意图，再同步游戏侧字段；后一步失败不撤销已保存的意图。
进程入口 `uv run --directory python-backend python -m src.headless` 提供 `call` 与 `serve --stdio`，见
[CLI 协议](../../../docs/rust-feasibility/headless-cli.md)。本层不负责传输、界面状态或格式化文案。

全局设置由 `AppService.settings_view` 聚合查询；CLI 校验 JSON 表单并转换为
`StartupOptions` / `RunOptions`，复用 `apply_startup_options` / `apply_run_options`
保存。关机能力由 CLI 补充到响应，设置保存不触发运行。

## 脚本管理

`script_service` 统一提供 `add / remove / update / reorder`；`AppService` 仅作薄委托。
各操作使用 `InvalidScript` 表示写入前的输入或状态错误；重复导入 EXE 使用其子类
`DuplicateScript`，便于批量导入单独计数。底层模块统一通过 `utils_config` / `utils_weekly` 调用。

工具栏通过 `AppService.resolve_script_target(script_name, target)` 查询 URL、绝对路径
或不可用原因；只接受官网/B 站/GitHub、脚本目录、日志目录和配置文件六类目标。
业务路径规则复用原接口，操作系统关联打开由前端负责，不含游戏启动操作。

`ScriptEdit` 表达一次完整编辑：编辑前标识、展示名、助手配置字段、每周超时、原生任务开关。
它只承载输入；`frozen=True` 禁止字段重新绑定，不提供深层不可变或事务保证。

Python GUI 收集 `ScriptEdit`，先经 `AppService.validate_script_edit` 校验；无效时保留弹窗和输入。
确认后调用唯一保存入口 `AppService.update_script(edit)`，由其薄委托 `script_service.update`。
该流程重新校验最新配置，并统一执行：

1. 更新 `config.yml` 的脚本条目，取得保存后的标识。
2. 标识变化时迁移 `weekly.yml` 两段，再保存每周超时。
3. 路径或标识变化时初始化子脚本配置。
4. 按保存后的标识写原生任务开关。

`script_service` 在本次读取的配置上完成条目修改，交给 `utils_config.save_config` 写盘；`utils_weekly` 负责每周参数的具体读写，配置适配器负责原生配置。
GUI 不编排这些步骤；CLI 如需调用，在传输边界构造 `ScriptEdit`，服务层不接收 JSON 协议对象。
写入失败立即传播异常，后续步骤不执行，已完成的写入不回滚，也不自动重试。
只改参数、超时、游戏路径或 exe 的展示名，以及无改动保存，都不强制对齐模板。
适配器首次构造时的初始化、启动预热和新增脚本的既有行为保持不变。

添加按「助手条目 → 每周默认参数 → 初始化」执行；删除按「助手条目 → 每周清理」执行，源文件保留。
排序只更新助手列表顺序。各操作按最新配置检查重复、最后一个脚本和完整顺序；过期排序拒绝写入。
快捷方式解析、类型推断和新增名称去重均归添加流程。编辑预校验和保存各自检查当时的配置，
保存内部的重名检查与条目修改共用一次读取；这不提供跨进程文件锁或事务保证。

CLI 表单通过 `script_edit_view` 读取；`script.edit_save` 在传输边界构造 `ScriptEdit`，
调用统一保存入口后将新标识包装为协议结果。`InvalidScript` 返回写入前的输入错误；
保存阶段异常提示可能已部分写入。手动勾选由 GUI 持有，不加入本层持久化配置。

`python-backend/src/link.py` 统一关联目标查询，`resolve_launch_target` 解析当前脚本/游戏启动目标；Python 脚本
复用 `build_script_command`，游戏复用手填路径优先的 `get_game_exe_path`，实际启动由
前端进行。单独启动不走批量调度链，保持原版行为；不传整个父进程环境或 shell 命令字符串。

`AppService.run_view/prepare_run` 汇总运行信息并在确认后保存选项；headless 负责 JSON
校验和独立 `src.headless run` 进程描述，不在持久 CLI 内执行长链。独立入口通过 stdin
接收无凭据的配置快照，交给 `chain_service.run_batch` 复用 schedule_run，并持有运行租约；
取消或 prepare 失败不启动。

## 手动更新

`AppService` 装配 `src.update.service.UpdateService`，薄委托本地状态读取、检查、下载和安装交接。
同模块的 `UpdateSession` 保留 CLI 更新会话状态，并使用 `AppService.jobs` 执行耗时操作。
更新协议、运行锁、安装事务和独立更新器集中在 [python-backend/src/update](../update/README.md)，无 Qt 依赖。
GUI 的弹窗和工作线程保留在 `python-backend/src/gui`，经 AppService 调用更新服务。

## 配置迁移

配置迁移只负责文件搬运，目录正确性及上游版本兼容性由用户保证。
ZIP 结构固定为 `scripts/<脚本名>/<相对路径>`，无清单或版本协议；
旧 ZIP 中的清单和自身配置目录直接忽略。备份目录中新增加的文件自动收录。

换机时先配置新机器的脚本路径，再选择 ZIP 恢复。同名文件覆盖，额外文件保留；
未配置目录的脚本跳过并列出，之后配置好路径可以再次恢复。唯一的字段处理是复用适配器已有声明，
保留本机游戏路径（包括空值）；本机文件或字段缺失时，不导入旧机器路径。
仅解析承载游戏路径的 JSON/YAML，其余文件原样复制。路径配置解析失败会停止恢复，
保留该文件现值并报告已完成数量。ZIP 可以用普通解压工具直接取出配置。

恢复前会把本次已有目标保存为另一个普通 ZIP，写入单个文件时先写完临时文件再替换。
写入失败报告已完成数量和恢复前 ZIP 位置，不做整批自动回滚；请在子脚本停止后操作。

## 依赖方向

```
launcher.py CLI  ┐
                 ├─▶ AppService（组合根）─┬─▶ script_service（脚本管理）─┬─▶ utils_config（助手配置）
                                          │                          ├─▶ utils_weekly（每周参数）
                                          │                          └─▶ config 适配器（初始化/任务开关）
MainWindow  GUI  ┘                        ├─▶ daily_config 模块函数（副本 / 周本声明，src.config）
                                          └─▶ chain_service ─▶ chain_gen / schedule / utils_runner
                                                  └─▶ src.utils.utils_weekly（周常参数读写）
```

调用方不感知 weekly 同步、链合法性校验、runner 命令构造等细节，全部内聚在 service/。

`utils_shutdown.py` 不得模块级依赖 GUI 层：否则 `schedule → utils_shutdown →
gui.dialogs → app_service → chain_service → schedule` 成环，确认窗实现于 `python-backend/src/gui/shutdown_dialog.py`，`utils_shutdown` 仅延迟 import 它。

## 每日运行

在配置弹窗启用每日计划时注册当前用户的 Windows 交互任务（需管理员权限），仅记录程序入口和每日时间。计划默认关闭，默认时间为 04:10，对所有脚本生效。GUI 关闭仍会按时触发，电脑需保持开机并登录；不唤醒、不补跑错过的时间。

`--run-daily` 每次读取 daily_run（含独立 run_options 块），以 now 运行当天全部脚本的链；手动脚本 enabled 不参与筛选，运行选项也取每日计划独立配置（不再回落手动 RunOptions）。计划已关闭或没有可运行的脚本则无动作。只改副本、超时或运行选项无需更新系统任务，修改时间或开关才更新任务；暂停保留时间。旧 CLI `--schedule-run HH:MM[:SS]` 保留一次性等待用途（可带秒，便于精确等待或集成测试用「当前 + 几秒」）。

系统任务按安装目录和用户命名。请保持安装目录和可执行文件路径稳定；移动安装前先关闭旧计划，再在新位置启用。任务更新成功才写配置，写入失败时恢复原任务。

每日计划的聚合查询与保存统一归 daily_plan；headless 校验 JSON 表单并转换为
DailyPlanOptions，经 AppService.apply_daily_plan 保存，同时将 CLI 入口交给 WindowsDailyTask。
同一个任务可迁移到无 Qt headless daily；entry_matches 参与同步判断，避免旧入口沿用。
迁移写盘失败恢复 read 阶段保存的原 XML；原 Qt 调用不传 entry，保留原入口与恢复语义。

CLI 备份/恢复通过 AppService.jobs 的 JobExecutor 调用原服务；只做调度与结果保留，
不重写 ZIP 搬运逻辑。stdio 会话串行轮询，EOF 等任务结束再释放运行租约；GUI 禁止普通关窗
打断恢复，后台异常记录日志并保留可展示的部分完成详情。

## 资源与启动目标

`src.link.resolve_script_target` 统一解析主页、B 站、GitHub、脚本目录、日志目录和配置文件，返回 URL、绝对路径或不可用原因。`src.link.game_icon_path` 按需读取游戏路径，图标提取仍由前端负责。

`resolve_launch_target` 统一解析当前脚本或游戏的启动方式。外部程序使用系统关联打开；Python 脚本复用 Runner 命令，保留参数、工作目录和环境覆盖项。调用方继承自身环境并应用覆盖项，不经接口传递整个进程环境。

这些查询不打开文件、不启动进程。Python GUI 直接调用 AppService，无须经过 CLI；其它前端可通过同一 service 获取目标。

`AppService` 默认装配 Qt 发行版的更新服务，Rust headless 入口显式传入 `frontend="rust"`。直接更新调用与后台更新会话共用同一个 `UpdateService`，不为 Python GUI 额外装配 Rust 更新实例。
