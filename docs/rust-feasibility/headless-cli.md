# 无 Qt 任务卡 CLI

入口是 `python -m src.headless`，从项目根运行，经 AppService 复用任务卡 service。
支持脚本列表、日常/周常查询与编辑、写后真实反读；本 PR 仅提供进程协议，GUI 接入另行提交。

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
```

响应恰有 `result` 或 `error` 之一，并回传 id：

```json
{"protocol_version":1,"id":"list-1","result":{"scripts":[]}}
{"protocol_version":1,"id":"edit-1","error":{"code":"invalid_params","message":"一级选项不存在: 示例","refresh_required":false}}
```

客户端自行使用唯一 id，并关联当前脚本选择；切换到 B 后，A 的迟到响应不得刷新 B。
首期无推送事件、后台 job、自动重试或跨进程写入事务。

| 方法 | 参数 | 返回 |
| --- | --- | --- |
| `app.snapshot` | `{}` | `scripts`：按配置顺序给出 `script_name/display_name/script_path/adapted/script_data`；script_data 为原脚本条目，供现有 GUI 展示；不扫描所有外部脚本 |
| `script.view` | `script_name` | `script` 摘要、`dailies` 和 `weeklies` |
| `daily.select` | `script_name/daily_name/task_name`，可选 `sequence` | 写入后重新查询得到的完整 `script.view` |
| `daily.enable` | `script_name/daily_name/enabled`（布尔） | 修改开关后的完整 `script.view`，不改变已选副本 |
| `weekly.select` | `script_name/weekly_name/task_name` | 校验当前物化菜单并写入，返回 `script.view` |
| `weekly.start` | `script_name/weekly_name/start_day`（整数 0…7） | 先保存周常意图，再同步游戏侧配置，返回 `script.view` |

日常条目沿用适配器反读字段：`name/task/sequence/enabled`，另附 `options`。
本地与 CLI 任务卡共用展示规则，响应不再对反读字段改名或嵌套。
物化选项仍使用 `display_name/physical_name/options.values`，最多两级。
提交 `task_name` 为一级展示名，`sequence` 为二级 `physical_name`，必须原样保留 JSON 类型。
例如鸣潮的整数 `1` 不接受 `true` 或字符串 `"1"`；崩铁的培养目标接受布尔 `true/false`，
不接受整数 `1/0`。无二级选项时省略 sequence 或传 null。

`task/sequence` 保留现有适配器反读语义：未选择或无数据为 null；
单字段资源选择（如终末地）可能直接将最终副本名放在 task，sequence 为 null。
`enabled=null` 表示没有可反读的开关状态（无开关或配置尚不存在），不应强行显示为禁用。
`daily.select` 沿用“选择后启用该日常”的原行为。动态资源不存在或选项已消失时拒绝写入。

周常条目：`name/options/task/start_day`；无选项组时 options 为 null。
start_day 为 `0`（不启用）、`1…7`，或 null（未设置），三者不同。
尚未开放设置、运行或更新动作。
自定义脚本返回 `adapted=false` 与空日常列表；未知脚本名返回错误。

| 错误码 | 含义 |
| --- | --- |
| `parse_error` | 非法 JSON、重复字段、NaN/Infinity；id 为 null，可继续发送下一条 |
| `invalid_request` | 信封字段或 id 不合法 |
| `unsupported_version` | 不支持的协议版本 |
| `method_not_found` | 未开放的方法 |
| `invalid_params` | 参数缺失、多余、类型错误，或脚本/日常/选项不存在 |
| `operation_failed` | 配置/适配器操作失败；诊断在 stderr 与日志，写请求返回 refresh_required=true |
| `session_failed` | 启动或传输失败；id 为 null，退出码为 2 |

`refresh_required=true` 表示结果可能已经部分落盘，不能假定回滚。
例如副本写入成功但启用失败，或者写入成功而随后反读失败。
收到错误或进程意外退出后，先用 script.view 重读，再让用户决定是否重试；不得自动重放写请求。

## 生命周期与现有边界

- 根目录规则与现有助手相同：源码取项目根，冻结后取 EXE 所在目录；不以 cwd 定位配置，
  当前未引入 `--root`。首次启动仍会从模板生成缺失的主配置。
- `application_lease` 先通过更新闸门再初始化配置，运行共享锁覆盖整个会话；EOF/退出释放。
  日志与崩溃钩子照常安装，业务 stdout 重定向 stderr，协议单独写 stdout。
- AppService 只薄委托新增的 `task_service`，查询与修改复用同一套 Python 适配器。
  `script.view` 每次重读外部配置；适配器构造仍可能执行现有的模板对齐，周常读取仍可能迁移旧格式。
  因此查询并不承诺整个应用层绝无写盘副作用。
- 仅承诺这些新增后端方法不加载 Qt。
  旧 launcher、关机确认、更新器进程交接、
  CLI 打包仍是后续工作；没有据此宣称整个发布包可以移除 Python 或 Qt。

## 验证

`tests/test_headless.py` 使用独立子进程和临时根目录，导入钩子主动阻止 PySide6、shiboken6、
src.gui；覆盖实际 JSON/YAML 落盘与反读、未修改字段保留、整数/布尔/资源选项、
选择后启用、周常禁用与未设置、同进程外部修改反读、错误后继续处理、UTF-8、
退出码，以及更新闸门和会话租约释放。

```text
PYTHONPATH=src python -m unittest tests.test_headless -v
```

`tests/service/test_task_service.py` 验证开关校验不加载菜单或周常、写入后只聚合一次完整任务卡。
源码全量回归与格式检查按 [TESTING.md](../../TESTING.md) 执行；尚未验证独立 headless EXE。
