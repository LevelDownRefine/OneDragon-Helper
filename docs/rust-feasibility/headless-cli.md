# 无 Qt CLI 协议

入口为 `python-backend/src/headless.py`，经 AppService 复用业务。[jsonrpcserver](https://explodinglabs.com/jsonrpcserver/dispatch/) 处理 JSON-RPC 2.0 信封、绑定与响应，本项目负责方法白名单、表单转换、stdio 和生命周期。两套 GUI 共用协议；发行类型由安装清单决定。

## 进程与传输

```powershell
'{}' | uv run --directory python-backend python -m src.headless call app.snapshot
uv run --directory python-backend python -m src.headless serve --stdio
```

- `call METHOD` 从 stdin 读一个参数对象或数组直到 EOF，返回 id=1 的响应；解析/协议失败的 id 为 null。退出码 0 成功、1 请求失败、2 启动或用法错误。
- `serve --stdio` 使用 UTF-8 JSON Lines，每行一个请求/响应并立即 flush，按输入顺序执行。无 ready 事件，首个 `app.snapshot` 成功即就绪。
- stdout 只输出协议，业务输出及诊断走 stderr；客户端须同时消费两个流。无网络端口、推送或自动重试。
- 标准位置参数、batch 和 notification 均支持；notification 不响应。id 可为字符串或整数，不接受布尔；空字符串合法。
- 正常 EOF 处理完已收请求及后台任务后退出 0，即使会话内有失败；启动/传输失败退出 2。

```json
{"jsonrpc":"2.0","id":1,"method":"script.view","params":{"script_name":"ok-ww"}}
{"jsonrpc":"2.0","id":2,"result":null}
{"jsonrpc":"2.0","id":3,"error":{"code":-32002,"message":"操作失败，详情见 stderr 或助手日志","data":{"refresh_required":true}}}
```

响应恰有 result/error 之一并回传 id。`result:null` 仍是成功，不能按真假判断。前后端应使用同一版本，旧 `protocol_version:1` 不支持。

## 方法

参数用斜线分隔字段名；`{}` 表示无参数。后台方法仅供 serve，启动返回 job id，业务结果由 job.poll 获取。

| 方法 | 参数 | 返回或作用 |
| --- | --- | --- |
| app.snapshot | {} | scripts 摘要及默认图标，不扫描所有外部脚本 |
| settings.view / startup.view | {} | 启动、计划开关、运行选项及关机能力，不查系统任务 |
| settings.startup_save | options | 保存 enabled/delay_seconds（1～3600），返回 null |
| settings.run_save | options | 保存完整 RunOptions，返回 null |
| run.view | script_names | 选择、无效原因、选项与关机能力，授权码为空 |
| run.prepare | script_names/options/confirm_invalid | 保存选项，返回独立运行命令与 stdin 数据 |
| run.saved | script_names | 以已存选项构造运行命令，不保存、不启动 |
| plan.view | {} | 计划及系统任务实际状态；读取失败有 state_error |
| plan.save | plan | 保存 enabled/target_time/run_options，返回 null |
| backup.start | {} | 开始备份，返回 job id |
| restore.start | zip_path/confirmed | confirmed 须为 true，返回 job id |
| job.poll / job.cancel | job_id | 查询任务 / 请求取消，后者返回 bool |
| update.view | {} | 本地版本、支持状态、上次结果和会话状态，不联网 |
| update.check | {} | 后台检查，结果 release（version/notes/size）或 null |
| update.download | {} | 下载会话中的版本，完成结果为 version |
| update.install | {} | 交接已校验包，完成结果为 version/ready |
| script.view | script_name | script 摘要、dailies、weeklies |
| script.target | script_name/target | URL、绝对路径或 unavailable/reason |
| script.launch_target | script_name/target | 单独启动目标；target 为 script/game，不执行启动 |
| script.edit_view | script_name | script、script_name、weekly_timeouts、switches、task_options |
| script.edit_save | script_name/display_name/config_patch/weekly_timeouts/switches，可选 task_options | 保存表单，返回新 script_name |
| script.add | file_path | 添加脚本，返回 script_name/display_name，不运行文件 |
| script.remove | script_name | 移除助手条目及每周设置，保留源文件；至少留一项 |
| script.reorder | script_names | 按完整唯一标识列表重排，拒绝过期快照 |
| script.icon_path | script_name | script_name/path，缺失时 path=null |
| wallpaper.current / wallpaper.view | script_name | 来源、模式、路径、token 和缓存状态 |
| wallpaper.set | script_name/file_path | 保存映射，null 恢复默认；不复制或删除源文件 |
| wallpaper.cache | script_name/token/jpeg_base64 | 保存 JPEG 缓存，旧 token 返回 false |
| daily.select | script_name；daily_name/task_name/sequence 默认 null | 选择副本并启用已有开关，返回 null |
| daily.enable | script_name/daily_name/enabled | 只改开关，返回 null |
| weekly.select | script_name/weekly_name/task_name | 选择副本，返回 null |
| weekly.start | script_name/weekly_name/start_day | 先保存意图再同步原生字段，返回 null |

协议校验信封、允许字段和表单类型，不重复适配器取值规则。RunOptions 定义及字段范围见 [schedule.py](../../python-backend/src/service/schedule.py)；计划、备份、更新的业务边界见 [服务层](../../python-backend/src/service/README.md)。

## 数据与保存契约

日常为 `name/task/sequence/enabled/options`，周常为 `name/task/options/start_day`。可空字段仍须明确返回，缺失不等于 null。仅子菜单 `Choice.options` 可省略。

- `enabled=null` 表示无可反读开关；`start_day=0` 禁用、1…7 为星期、null 未设置。
- 选项使用 display_name/physical_name/options.values。task_name 为一级展示名，sequence 通常为二级物理值；不转换字符串、整数和布尔。
- 未选择的 task/sequence 为 null；单字段选择可能直接在 task 返回最终值。空日常选择、无开关启停等沿用适配器的 no-op，不统一改成错误。
- 自定义脚本查询返回 adapted=false 和空任务列表；未知标识查询报错。写入语义仍归原接口。
- `script.view` 重读原生配置，可能触发已有初始化或迁移；菜单查询不触发脚本级初始化。

`script.edit_save.config_patch` 必须含：

| 类型 | 字段 |
| --- | --- |
| 字符串 | script_path、script_type、script_arguments、check_done、game_process_name、game_path、game_arguments |
| 布尔 | kill_script_after_done、kill_game_after_done、block |
| 0～2147483647 整数，拒绝布尔 | no_log_timeout_seconds、no_log_max_retries |

weekly_timeouts 恰为七项 0～86400 整数或 null；null 沿用默认，低于 10 秒保留运行器原语义。switches 为任务名到布尔的映射；task_options 为变化字段 id 到值的映射，省略视为空。后者的字段类型和候选由 [选项声明](../../python-backend/src/config/task/task_options.md) 校验。

预校验失败不写盘；完整保存可能部分完成，顺序归 script_service。保存成功后重读，改名后采用新标识；失败保留草稿并刷新列表/表单，不能自动重放。

`script.target.target` 为 home/bili/github/folder/log/configfile。单独启动返回 association/path、command/program/args/cwd/env 或 unavailable/reason；env 仅含相对父进程的修改项。前端显式启动，不套用批量运行的参数与前后动作。

壁纸优先自定义、脚本声明、渐变；自定义文件缺失时显示渐变但保留选择。前端负责解码、方向和缩放，缓存经 service 写盘，JPEG 上限 4 MiB。token 包含规范化路径、大小和修改时间，过期 token 不写入。

## 错误与恢复

| code | 含义 |
| --- | --- |
| -32700 | JSON 解析失败，包括重复字段及 NaN/Infinity |
| -32600 | 信封、版本、id、params 容器非法，或 call 使用后台方法 |
| -32601 | 方法未开放 |
| -32602 | 参数绑定或表单预校验失败 |
| -32603 | 协议库内部错误 |
| -32002 | 业务操作失败，诊断见 stderr/日志 |
| -32003 | 后台任务忙，只接受 poll/cancel |
| -32004 | 启动或传输失败，id=null，退出码 2 |

助手错误的 `error.data.refresh_required=true` 表示可能已部分落盘，不保证回滚。标准错误 data 可能是库诊断字符串；内部、未知或损坏错误均应保守刷新。

断连后只重读状态，不重放写入、启动或自动运行；切换脚本时以身份及选择代数过滤迟到响应。刷新失败与已确认的写入分别处理，不能因此再次保存。

## 后台任务

每个 serve 会话最多一个进行中任务，只保留最近结果。state 为 running/succeeded/failed/cancelled；启动返回 id 不代表完成，旧会话 id 不可复用。

任务期间只允许 job.poll/job.cancel。备份、恢复和安装不可取消；更新检查/下载可请求取消，返回 true 仅表示已发送意图，须继续轮询至终态。EOF 等待不可取消任务完成，对可取消更新先请求取消再等待，最后释放运行租约。强杀不能保证整批回滚。

更新 URL、版本和待安装目录由服务保管，前端不得回传替换。安装 ready 后禁止再次检查/下载/安装，前端退出；失败保留已校验包供显式重试。

## 独立运行与生命周期

`run.prepare` 返回 command 目标、`console:true` 和 input JSON（script_names/options），不在服务进程启动。凭据不进入命令行或返回值，沿用安全存储。

`src.headless run` 在独立进程从 UTF-8 stdin 读对象至 EOF，持运行锁执行 schedule_run；它不是 RPC 方法，GUI 退出不终止它。Windows 新控制台承接 stdout/stderr，stdin 只交付参数。

`daily --shutdown-ui 前端路径` 每次读取当前每日计划与全部脚本，暂停时无动作，不接受手动勾选。系统任务保存与回滚归 service。

关机确认使用 `ODH_SHUTDOWN_UI` 及可选 JSON 字符串数组 `ODH_SHUTDOWN_UI_ARGS`，直接调用「程序 + 固定参数 + --shutdown-confirm 秒数」。只有退出码 42 确认，0、异常、超时或无效入口均取消；显式入口失效不回退 Qt。确认进程不执行关机，延迟 0 不关机。

配置根目录为源码根或 EXE 目录，不依赖 cwd；首次启动生成缺失配置。application_lease 覆盖初始化及会话，退出释放。自动运行在每日计划启用、演示、截图和 `--after-update` 下跳过，重连不再次触发。

冻结 CLI 保留 call/serve/run/daily，旧参数经 `legacy -- 参数` 转发。Rust 在建窗前转发 `--version/--selftest/--schedule-run` 等并保留退出码；源码 `--project-root/--python` 放在业务参数前。无动作 CLI 返回 2，不创建 Qt 窗口。

测试入口见 [测试指南](../TESTING.md)；协议用例在 `python-backend/tests/test_headless.py`，冻结验证在 `python-backend/tests/exe/test_headless_exe.py`。
