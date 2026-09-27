# 无 Qt 任务卡 CLI

入口是 `python -m src.headless`，从项目根运行，经 AppService 复用任务卡 service。
支持脚本列表、日常/周常查询与编辑。写入与查询是独立请求；GUI 接入另行提交。

## 两种调用方式

一次调用：

```powershell
'{}' | python -m src.headless call app.snapshot
```

`call METHOD` 从 stdin 读一个 JSON 参数对象（可以多行），读到 EOF 后输出一个响应，
响应 id 固定为 `1`。成功退出码 `0`，请求失败为 `1`，会话/启动失败为 `2`。
命令行解析错误也为 `2`，由 argparse 在 stderr 输出用法。

GUI 启动并复用一个进程：

```text
python -m src.headless serve --stdio
```

stdin/stdout 使用 UTF-8 JSON Lines，每行一个请求或响应，立即 flush。
客户端同时消费 stdout 和 stderr，不使用 shell 拼接请求或固定临时结果文件。
不监听网络端口；请求按输入顺序串行执行。关闭 stdin 后处理完已收到的请求并退出，
正常 EOF 退出码为 `0`，即使会话中有请求失败；客户端须检查每个响应。
没有 ready 事件，首条 `app.snapshot` 成功响应即可视为就绪。

## v1 请求与响应

请求恰好含四个字段；id 是非空字符串或整数，不接受布尔；版本必须为整数 `1`：

```json
{"protocol_version":1,"id":"list-1","method":"app.snapshot","params":{}}
{"protocol_version":1,"id":"card-1","method":"script.view","params":{"script_name":"ok-ww"}}
{"protocol_version":1,"id":"edit-1","method":"daily.select","params":{"script_name":"ok-ww","daily_name":"每日任务","task_name":"凝素领域","sequence":1}}
{"protocol_version":1,"id":"card-2","method":"script.view","params":{"script_name":"ok-ww"}}
```

响应恰有 `result` 或 `error` 之一，并回传 id：

```json
{"protocol_version":1,"id":"list-1","result":{"scripts":[]}}
{"protocol_version":1,"id":"edit-1","result":null}
{"protocol_version":1,"id":"bad-1","error":{"code":"invalid_params","message":"参数字段缺失或包含不支持的字段","refresh_required":false}}
```

客户端自行使用唯一 id，并关联当前脚本选择；切换到 B 后，A 的迟到响应不得刷新 B。
首期无推送事件、后台 job、自动重试或跨进程写入事务。
四个任务卡写操作成功（包括原接口的空操作）返回 `result:null`；字段存在即表示成功，不能按结果的真假判断。
需要回显时，客户端在收到成功响应后再请求 `script.view`。刷新失败与写入失败分别处理，
不因刷新失败重放已确认的写请求。

| 方法 | 参数 | 返回 |
| --- | --- | --- |
| `app.snapshot` | `{}` | `scripts`：按配置顺序给出 `script_name/display_name/script_path/adapted/script_data`；script_data 为原脚本条目，供现有 GUI 展示；不扫描所有外部脚本 |
| `settings.view` / `startup.view` | `{}` | 启动选项、每日计划是否启用、手动运行选项与关机能力；不查询系统任务 |
| `settings.startup_save` | `options`（enabled/delay_seconds） | 保存启动选项，返回 null；预校验 1～3600 秒 |
| `settings.run_save` | `options`（完整 RunOptions） | 独立保存运行选项，返回 null；不启动 |
| `run.saved` | `script_names` | 只读已存运行选项，返回独立运行命令；不保存、不启动 |
| `plan.view` | `{}` | 独立计划、实际任务状态/读取错误、平台及关机能力 |
| `plan.save` | `plan`（enabled/target_time/run_options） | 保存计划及系统任务，返回 null；不立即运行 |
| `run.view` | `script_names` | 当前选择、无效脚本原因、运行选项（授权码始终为空）、关机支持状态 |
| `run.prepare` | `script_names/options/confirm_invalid` | 保存已确认选项，返回独立运行命令及 stdin JSON；不会在服务进程启动调度 |
| `script.view` | `script_name` | `script` 摘要、`dailies` 和 `weeklies` |
| `script.target` | `script_name/target` | 只解析工具栏的 URL、路径或不可用原因，不执行打开动作 |
| `script.launch_target` | `script_name/target`（script 或 game） | 解析单独启动目标；与工具栏普通资源查询分开，本接口不执行启动 |
| `script.edit_view` | `script_name` | 原脚本条目 `script`、标识 `script_name`、七日 `weekly_timeouts` 和 `switches`（name/enabled） |
| `script.edit_save` | `script_name/display_name/config_patch/weekly_timeouts/switches` | 保存完整脚本表单，返回 `{"script_name":"保存后的标识"}` |
| `script.add` | `file_path` | 解析脚本/快捷方式并添加，返回 `{"script_name":"新标识"}`；不运行文件 |
| `script.remove` | `script_name` | 删除助手条目及每周设置，保留源文件，返回 null；至少保留一个条目 |
| `script.reorder` | `script_names` | 按完整唯一标识列表重排，返回 null；拒绝重复或过期快照 |
| `daily.select` | 必填 `script_name`；可选 `daily_name/task_name/sequence`，默认均为 null | 沿用原日常选择接口，返回 null |
| `daily.enable` | `script_name/daily_name/enabled` | 修改目标开关，不改变已选副本，返回 null |
| `weekly.select` | `script_name/weekly_name/task_name` | 沿用原周常选择接口，返回 null |
| `weekly.start` | `script_name/weekly_name/start_day` | 先保存周常意图，再同步游戏侧配置，返回 null |

协议层校验信封、方法白名单、参数对象及必填/允许的字段，不复制业务取值校验。
参数值原样传给 AppService，四个写入口再直接转发原 GUI 接口；返回值不转换，也不附带查询。

日常条目沿用适配器反读字段：`name/task/sequence/enabled`，另附 `options`。
本地与 CLI 任务卡共用展示规则，响应不再对反读字段改名或嵌套。
物化选项仍使用 `display_name/physical_name/options.values`，最多两级。
选择副本时 `task_name` 为一级展示名，`sequence` 通常为二级 `physical_name`；
原适配器也接受静态二级展示名（如鸣潮「梦州-迅刀」映射为整数 `1`）。
CLI 不转换字符串、整数或布尔值，字段类型及取值校验仍由原适配器负责。
无二级选项时省略 sequence 或传 null；是否需要二级值由相应机制类判断。

`task/sequence` 保留现有适配器反读语义：未选择或无数据为 null；
单字段资源选择（如终末地）可能直接将最终副本名放在 task，sequence 为 null。
`enabled=null` 表示没有可反读的开关状态（无开关或配置尚不存在），不应强行显示为禁用。
`daily.select` 沿用“选择后启用该日常”的原行为。任务名省略、null、空字符串或「未选择」时跳过，
未适配脚本也跳过。动态资源二级值不额外做菜单成员校验；无开关日常的启停沿用原空操作。

周常条目：`name/options/task/start_day`；无选项组时 options 为 null。
start_day 为 `0`（不启用）、`1…7`，或 null（未设置），三者不同。
尚未开放更新动作。
工具栏 `script.target` 的 target 为 `home/bili/github/folder/log/configfile`。
成功目标为 `{"kind":"url"或"path","value":"..."}`，本机缺失资源为
`{"kind":"unavailable","reason":"..."}`；路径为绝对路径。链接沿用资源声明及原 GUI
通用回退，日志与配置文件沿用现有解析器。调用方用系统关联打开；此查询不会启动游戏，
也不把路径或配置内容拼入 shell 命令。查询异常的 `refresh_required` 为 false。
查询自定义脚本返回 `adapted=false` 与空日常列表；查询未知脚本名返回错误。
写入的未知脚本、未知周常等情况按原接口处理，不统一改为查询错误。
例如无副本选择的周常选择为空操作；设置未知周常起始日仍保存助手侧意图，跳过游戏侧同步。

`script.edit_save` 的 config_patch 必须包含 script_path、script_type、script_arguments、
check_done、game_process_name、game_path 六个文本字段，以及 kill_script_after_done、
kill_game_after_done、block 三个布尔字段。weekly_timeouts 恰为七项 0～86400 整数或 null；
null 沿用默认超时，低于 10 秒的值保留原运行语义。switches 为任务名到布尔的映射。
表单预校验失败返回 invalid_params、refresh_required=false，不写盘。
保存顺序复用 update_script → init_script_after_edit → set_script_switches，后续失败可能已部分写入；
客户端保留草稿、刷新 app.snapshot（改名可能改变身份），要求重新读取表单后再由用户保存。
正常保存后也须重新查询，不把旧身份继续用于任务卡请求；取消表单无需请求。

列表操作同样区分预校验失败和部分保存失败，客户端均通过 app.snapshot 重读；
不会因为刷新失败重复添加/删除。手动勾选与控制模式只在 GUI 内存中，不提供写配置接口；
脚本重排按身份保留勾选，新条目默认启用，重启回到全选。每日计划不读取此状态。

`script.launch_target` 返回 `association/path`、`command/program/args/cwd/env` 或
`unavailable/reason`。Python 脚本命令由原 build_script_command 生成，env 只返回相对
父进程的修改项，不传整个环境；external 脚本和游戏沿用系统关联打开。
游戏路径沿用手填优先、原生配置兜底规则。前端显式点击后才启动，不自动重试；
单独启动保持原版语义，不应用批量链运行参数、完成检测、超时或前后动作。

| 错误码 | 含义 |
| --- | --- |
| `parse_error` | 非法 JSON、重复字段、NaN/Infinity；id 为 null，可继续发送下一条 |
| `invalid_request` | 信封字段或 id 不合法 |
| `unsupported_version` | 不支持的协议版本 |
| `method_not_found` | 未开放的方法 |
| `invalid_params` | params 不是对象、参数字段缺失/多余，或显式查询引用了未知脚本 |
| `operation_failed` | 配置/适配器操作失败；诊断在 stderr 与日志，写请求返回 refresh_required=true |
| `session_failed` | 启动或传输失败；id 为 null，退出码为 2 |

`refresh_required=true` 表示结果可能已经部分落盘，不能假定回滚。
例如副本写入成功但启用失败，或周常意图已保存但游戏侧同步失败。
适配器抛出的取值/类型错误同样属于 `operation_failed`；协议层不重建业务异常分类。
收到错误或进程意外退出后，先用 script.view 重读，再让用户决定是否重试；不得自动重放写请求。

## 全局设置与自动启动

父配置窗与运行选项分别保存。嵌套 `settings.run_save` 成功后反读 settings.view，
仅更新运行选项，保留父表单启动草稿；失败不重放，刷新失败须提示可能已保存。
取消不发写请求。手动保存设置不产生启动命令。

Rust 首次任务卡就绪后请求 startup.view；每日计划启用时跳过启动倒计时。
倒计时确认后调用 run.saved，以最新配置构造命令，保持原无人值守启动跳过无效脚本告警的语义。
查询失败或重连不再次自动启动，更新后的 `--after-update`、演示/截图模式也跳过。

## 每日计划

plan.save 校验完整表单，复用 apply_daily_plan 注册当前用户、安装目录对应的同一个任务。
回读除开关/时间外还检查命令、参数、工作目录；旧 Qt 入口即使时间未变也会修复。
系统任务成功后才写计划，写盘失败以原 XML 恢复真实任务，不凭配置猜测旧入口；
原先未注册则删除新任务。取消不请求保存，状态读取失败返回 state:null 与 state_error。

任务命令为 `python -m src.headless daily --shutdown-ui Rust前端绝对路径`，冻结后省去 -m。
此入口持有运行锁，读取当时 daily_run 的全部脚本与独立选项，不接收手动勾选；
已暂停则无动作。关机确认环境显式从参数恢复，其他任务语义沿用原服务。
Rust UI 保存后回读实际状态，更新父窗每日计划开关并保留未提交的启动草稿。

## 批量运行

`run.view` 接受当前列表内非空、无重复的脚本标识；手动勾选仅由前端传入。
`run.prepare` 严格验证 RunOptions 完整字段、类型和范围；无效脚本须显式确认跳过，
保存选项后返回 command 目标，增加 `console:true` 和 `input` 字段。
input 是 `{"script_names":[...],"options":{...}}` 的 JSON 文本；选项重新读取、授权码不回传，
凭据沿用现有安全存储。取消无需调用 prepare；写入失败可能部分完成，不能自动重试或启动。

独立入口 `python -m src.headless run` 从 UTF-8 stdin 读一个 JSON 对象直到 EOF，
在独立进程内复用 schedule_run，运行锁覆盖初始化与完整调度。它不是 stdio RPC 方法，
不会阻塞持久服务；GUI 退出不终止该进程。Windows 前端以 CREATE_NEW_CONSOLE 启动，
worker 将 stdout/stderr 绑定 CONOUT$，stdin 保留给参数；无 Qt 导入。
任务名、邮箱和凭据均不进入命令行。失败返回非零退出码，详细诊断在控制台和原日志。
Windows Rust 前端将自身绝对路径传入 `ODH_SHUTDOWN_UI`，prepare 将该变量显式转交运行进程。
运行后仍由原 post_run 最后一步触发确认，独立 Rust 进程 `--shutdown-confirm 秒数` 只显示
倒计时，不执行系统命令；只有退出码 42 表示确认，0 为取消，其他退出码/启动失败/超时也取消。
指定入口失效时不回退 Qt。未指定变量的原 Python GUI 保持原确认窗；无 Qt run 的启用校验
要求有效 Rust 入口。延迟 0 仍沿用原语义：不触发关机。

## 生命周期与现有边界

- 根目录规则与现有助手相同：源码取项目根，冻结后取 EXE 所在目录；不以 cwd 定位配置，
  当前未引入 `--root`。首次启动仍会从模板生成缺失的主配置。
- `application_lease` 先通过更新闸门再初始化配置，运行共享锁覆盖整个会话；EOF/退出释放。
  日志与崩溃钩子照常安装，业务 stdout 重定向 stderr，协议单独写 stdout。
- AppService 的查询委托 `task_service`，四个写入口直接调用原 GUI 对应方法。
  `script.view` 每次重读外部配置；适配器构造仍可能执行现有的模板对齐，周常读取仍可能迁移旧格式。
  因此查询并不承诺整个应用层绝无写盘副作用。
- 仅承诺这些新增后端方法不加载 Qt。
  旧 launcher、更新器进程交接、
  CLI 打包仍是后续工作；没有据此宣称整个发布包可以移除 Python 或 Qt。

## 验证

`tests/test_headless.py` 使用独立子进程和临时根目录，导入钩子主动阻止 PySide6、shiboken6、
src.gui；覆盖实际 JSON/YAML 落盘与反读、未修改字段保留、整数/布尔/资源选项、
独立写入确认与查询、默认参数/空操作、静态展示名转换、选择后启用、周常禁用与未设置、
同进程外部修改反读、错误后继续处理、UTF-8、
退出码，以及更新闸门和会话租约释放。

```text
PYTHONPATH=src python -m unittest tests.test_headless -v
```

`tests/service/test_task_service.py` 覆盖聚合查询；`tests/service/test_task_editing.py`
覆盖 CLI 入口直接转发原方法及既有写入行为。
源码全量回归与格式检查按 [TESTING.md](../../TESTING.md) 执行；尚未验证独立 headless EXE。
