# 发行版 CLI 操作契约

## 定位入口与传输

使用完整解压的安装包，不单独搬出 EXE。仅调用发行版 CLI 时，无需 Python、uv 或源码。

- Rust 版：`<安装根目录>/OneDragon-Helper-CLI.exe`。
- Qt 版：`<安装根目录>/_internal/cli/OneDragon-Helper-CLI.exe`。
- 配置根始终是安装根目录，不随当前工作目录改变。找不到 CLI 时先核对安装包版本与完整性，不用 GUI EXE 代替 RPC 入口。

以下 PowerShell 示例中的路径、脚本标识和选项应替换为本机查询结果：

```powershell
$cli = 'D:\OneDragon-Helper\OneDragon-Helper-CLI.exe'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $OutputEncoding
'{}' | & $cli call app.snapshot
'{"script_name":"实际标识"}' | & $cli call script.view
```

`call METHOD` 的 stdin 是**参数对象**，不是 JSON-RPC 信封；写完必须关闭 stdin（EOF）。返回一条 JSON-RPC 2.0 响应，通常 `id=1`。退出码 0 为请求成功、1 为请求失败、2 为启动或用法错误。

`serve --stdio` 保持一个进程，每行一个完整请求，响应按行读取；没有 ready 事件，首个 `app.snapshot` 成功即就绪：

```json
{"jsonrpc":"2.0","id":1,"method":"app.snapshot","params":{}}
{"jsonrpc":"2.0","id":2,"method":"script.view","params":{"script_name":"实际标识"}}
```

两种方式均使用 UTF-8，stdout 只含协议，stderr 为诊断，客户端须同时读取，不能合并后当 JSON 解析。响应包含 `result` 或 `error` 之一；`result:null` 仍然成功。`serve` 按顺序执行，无主动推送，正常 EOF 的退出码 0 不代表每个请求都成功。它是 JSON-RPC 接口，不是 MCP 服务。

## 查询身份、路径和任务

| 方法 | 参数 | 使用结果 |
| --- | --- | --- |
| `app.snapshot` | `{}` | `scripts[]` 含 `script_name/display_name/script_path/adapted/script_data`；后续传 `script_name`，不拿展示名代替 |
| `script.target` | `{"script_name":"…","target":"folder"}` | target 可为 `folder/log/configfile/github/home/bili`；返回 `kind=path/url,value` 或 `kind=unavailable,reason`，不打开目标 |
| `script.view` | `{"script_name":"…"}` | 返回 `script/dailies/weeklies`，当前配置和可选项均在响应内 |
| `script.edit_view` | `{"script_name":"…"}` | 返回 `script_name/script/weekly_timeouts/switches/task_options`，用于完整表单编辑 |

`folder` 是启动文件所在目录，启动器的实际工作目录仍需核实。`log` 是实时日志目录，不保证等于结果分析日志。`github` 未声明时会回退到助手仓库，不能直接认作子脚本仓库。CLI 启动会执行助手配置初始化，`configfile` 可能实例化子脚本配置适配器并写盘；独立检查使用 Skill 的 Python 工具直接读取文件。

日常条目为 `name/task/sequence/enabled/options`；周常为 `name/task/options/start_day`。`enabled=null` 表示没有可反读的独立开关；`start_day=null` 表示未设置。`adapted=false` 的自定义脚本可有空任务列表。`script.view` 可能触发既有原生配置初始化或迁移，不是执行结果查询。

## 日常与周常选择

名字和值均取自刚读到的条目及 `options.values`，保留 JSON 原始类型，不把数字、布尔统一转成字符串。

| 方法 | 完整参数形状 | 选择语义 |
| --- | --- | --- |
| `daily.select` | `script_name,daily_name,task_name,sequence` | `daily_name` 取条目 `name`；`task_name` 取一级选项 `display_name`；有子菜单时 `sequence` 取二级 `physical_name`，无子菜单传 null；选择会启用该日常已有开关 |
| `daily.enable` | `script_name,daily_name,enabled` | `enabled` 为布尔，只改开关，不改副本；仅对查询显示有开关的日常使用 |
| `weekly.select` | `script_name,weekly_name,task_name` | `weekly_name` 取条目 `name`，`task_name` 取选项 `display_name`，不传 `sequence` |
| `weekly.start` | `script_name,weekly_name,start_day` | 0 禁用，1～7 为周一至周日；先保存该条目的起始日，再同步适配的原生字段 |

```json
{"script_name":"实际标识","daily_name":"响应中的日常名","task_name":"一级展示名","sequence":"二级物理值"}
{"script_name":"实际标识","weekly_name":"响应中的周常名","start_day":1}
```

`daily.select` 的三个选择参数虽允许省略为 null，实际编辑应明确提供对应日常；空选择可能只是无操作。保存后重新 `script.view` 核对；单字段选择的最终值可能直接出现在 `task`，不是总在 `sequence`。

## 完整表单保存

`script.edit_save` 必填 `script_name/display_name/config_patch/weekly_timeouts/switches`，可选 `task_options`。先取 `script.edit_view`，保留未改值；不能只传变动的基础字段。

`display_name` 取 `script.display_name`；从 `script` 中选出以下 **12 个字段**组成 `config_patch`，不要把整份 `script` 原样塞进去：

| 类型 | 必须存在的字段 |
| --- | --- |
| 字符串 | `script_path,script_type,script_arguments,check_done,game_process_name,game_path,game_arguments` |
| 布尔 | `kill_script_after_done,kill_game_after_done,block` |
| 整数，0～2147483647 | `no_log_timeout_seconds,no_log_max_retries` |

`script_type` 只能是 `external/python`；`check_done` 只能是 `script_closed/game_closed/game_or_script_closed`。`script_path` 非空；非空 `game_path` 必须指向现存文件。若旧配置缺字段，先用本版本 GUI 保存一次补齐，不猜默认值。

- `weekly_timeouts`：恰好 7 项，按周一至周日排列，每项为 0～86400 整数或 null；null 沿用默认，低于 10 秒保留运行器原有语义。
- `switches`：将返回的 `[{name,enabled},…]` 转为 `{任务名:布尔,…}`，保留未改的状态；没有开关时传 `{}`。这类原生任务开关与 `daily.enable` 分开。
- `task_options`：**只提交改动的 `id → value`**，不是整份返回列表。字段 `type=bool/choice/multi` 分别传布尔、字符串、无重复字符串数组；候选取 `choices[].physical_name`，不用展示名。不改则省略或 `{}`。
- 路径或标识改变时，先保存并刷新，再改附带选项。成功返回新 `script_name`，后续改用它。

预校验错误不写盘；保存阶段失败可能部分落盘。遇到 `error.data.refresh_required=true`，先重新查询列表和表单，再决定处理；不自动重放原写入。普通保存是持久化修改，临时调整的恢复由调用方负责。

## 运行入口与选项

先调用 `run.view`，参数 `{"script_names":["实际标识A","实际标识B"]}`。名单必须非空、无重复且全为已知标识；返回按配置顺序排列的 `script_names`、`invalid[{name,reason}]`、`options` 和 `shutdown_supported`。

直接运行使用 legacy 入口，进程持续到执行链、内置重跑及后处理结束：

```powershell
& $cli legacy -- --schedule-run now --enable '实际标识A,实际标识B'
```

`--enable` 为逗号分隔的标识白名单，未知标识报错；省略、`all` 或空字符串表示全部。执行顺序取配置列表，不取参数顺序。`--schedule-run` 也接受 `HH:MM[:SS]`，表示进程内等待，不是创建每日系统计划。

legacy 的 `--mute/--unmute/--close-running` 仅在显式传入时开启，`--shutdown 秒数` 显式控制关机；不能把 `run.view.options` 当成这些参数已自动生效。内置重跑和邮件通知从已存配置读取。退出 0 仅表示调度入口结束，不证明每个任务成功；本轮结果仍需结合日志检查，`job.poll` 不跟踪此进程。

需要使用完整运行表单时：

- `run.saved`：参数 `script_names`，按已存选项返回运行目标，不保存也不启动。
- `run.prepare`：参数 `script_names/options/confirm_invalid`；**保存选项并返回运行目标，不启动**。`confirm_invalid` 为布尔，有无效脚本且为 false 时拒绝；true 表示已接受它们会在运行时跳过。
- 返回目标包含 `program/args/cwd/env/console/input`。按原值启动独立进程，将 `input` 以 UTF-8 写入 stdin 后关闭；`env` 是对父环境的增量，不是完整环境。`console=true` 要保留 Windows 控制台，`run` 的 stdout/stderr 会写到 `CONOUT$`，不能假定管道可捕获运行输出。

`options` 必须包含下列全部 11 个字段，禁止缺项、额外字段或类型转换；通常复制 `run.view.options` 后只改用户要求的项。下面是结构示例，不是应覆盖用户设置的推荐值：

```json
{
  "shutdown_enabled": false, "shutdown_delay": 0,
  "mute_enabled": false, "unmute_enabled": false,
  "close_running_enabled": true, "rerun_enabled": false,
  "notify_enabled": false, "email": "", "smtp_host": "",
  "smtp_port": "", "auth_code": ""
}
```

`shutdown_delay` 为 0～86400 整数；启用关机需要有效确认入口，延迟 0 不关机。必要时将 `ODH_SHUTDOWN_UI` 指向安装根的 `OneDragon-Helper.exe`。`smtp_port` 是字符串，非空时须为 1～65535；邮箱、SMTP 字段空串保留已有值，`auth_code` 空串不改系统凭据，查询也不会返回授权码。

## 其他操作导航

- 脚本增删排序：`script.add {file_path}`、`script.remove {script_name}`、`script.reorder {script_names}`；排序须传完整唯一名单。删除只移除助手记录，保留源文件且至少留一项。
- 每日计划：`plan.view {}` 读配置和系统任务实际状态；`plan.save {plan:{enabled,target_time,run_options}}` 完整保存，时间为 `HH:MM`，选项同上。计划运行全部脚本，不接受手动勾选名单；启用需有效 Windows 关机确认入口。
- 备份、恢复：在同一 `serve` 会话调用 `backup.start {}` 或 `restore.start {zip_path,confirmed:true}`，随后 `job.poll {job_id}` 直到终态。
- 更新：`update.view {}` 只读本地；`update.check {}` → 轮询 → `update.download {}` → 轮询 → `update.install {}` → 轮询，版本和下载目标由服务保管。安装返回 ready 后结束会话并退出前端，不再次发起更新。
- 每个 `serve` 会话最多一个后台任务，期间只接受 `job.poll/job.cancel`；state 为 `running/succeeded/failed/cancelled`，旧会话 job id 无效。备份、恢复、安装不可取消；检查和下载可请求取消，但仍须等终态。断连后重读状态，不自动重放启动或写入。
