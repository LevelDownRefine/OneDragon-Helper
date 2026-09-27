# 任务卡接口兼容性核对

基线为 #97 合并前的 AppService 与 GUI 调用。#97 增加的查询和编辑接口用于 CLI 接入，
六个入口全部保留。CLI 编辑入口复用 GUI 原接口的适配器与写入规则，
移除新增的前置校验和写后整卡查询，使两种入口的业务行为一致。

| #97 接口 | 原入口 / 数据来源 | 新增差异及原意 | 处理 |
|---|---|---|---|
| `app_snapshot` | `load_config`、`get_script_name`、`is_adapted` | 为 CLI 汇总脚本身份和原始配置；保留配置顺序与自定义脚本，不预热适配器 | 保留，属于新增查询能力 |
| `script_view` | `get_daily_map/readback`、`get_weekly_map/task/start_map` | 将菜单与原生状态合成普通字典；显式指定脚本，每次重新读取，不包含 GUI 的 chip 文案、默认显示值或菜单缓存 | 保留；这是原始数据查询，界面呈现仍由 GUI 负责 |
| `select_daily` | `set_script_daily_task` → `set_config` | 为 CLI 提前校验脚本及当前菜单，并写后返回整卡；额外拒绝空选择、静态二级展示名及未列入当前资源菜单的值 | 保留 CLI 入口，直接委托 `set_config`，可选参数默认值对齐原接口 |
| `enable_daily` | `set_script_daily_enabled` → `set_daily_enabled` | 为 CLI 检查布尔类型及开关可用性；预读全部日常，无开关或无法反读时直接拒绝，写后再读整卡 | 保留 CLI 入口，直接委托 `set_daily_enabled` |
| `select_weekly` | `set_script_weekly_task` → `set_weekly_task` | 为 CLI 校验周常和菜单；把不存在或不支持副本选择时的跳过改为异常，写后再读整卡 | 保留 CLI 入口，直接委托 `set_weekly_task` |
| `start_weekly` | `set_weekly_start_for` | 为 CLI 预检条目和日期；额外要求条目存在，日期失败由原 `AssertionError` 变为 `InvalidTaskSelection`，写后再读整卡 | 保留 CLI 入口，直接委托 `set_weekly_start_for` |

四个写接口的共同问题：写入已经完成后，整卡查询可能因另一条日常、周常或资源文件损坏而失败，
让一次成功写入表现为失败。菜单预检也会使一个原本只需目标配置的操作依赖无关文件。
这些都是额外的业务约束，并非序列化或 CLI 接入的要求。

CLI 日常参数 `daily_name` 对应原接口的 `daily_display_name`，值与类型原样传入。
四个 CLI 写接口和原接口一样返回 `None`，不转换异常；查询回显单独调用 `script_view`。

## 原写接口必须保留的行为

- 日常：未选任务（`None`、空字符串或「未选择」）直接跳过；自定义未适配脚本跳过。
  选择成功后启用该日常。静态二级选项允许展示名转物理值；动态资源的二级值不经菜单成员校验。
  需要二级值、字段类型及落点等规则仍由具体适配器判断，不在服务层统一放宽或收紧。
- 日常开关：只修改目标日常开关；无开关落点时不做事。未适配脚本、未知日常及损坏配置
  仍按原适配器报错，不统一转换异常。
- 周常选择：未知周常或机制未实现 `set_task` 时不做事。目前的周常声明均无副本选项，
  这一空操作行为同样属于原契约。
- 周常起始日：保留 `0=不启用`、`1…7=周一…周日` 的现有校验及异常类型。
  先保存 `weekly.yml` 中的意图，再同步游戏侧；不存在或无对应字段的周常跳过游戏侧同步。
  同步失败时保留已写意图并传播原异常，不额外回读，也不自动回滚。

## 查询边界

`app_snapshot` 和 `script_view` 不替换旧查询方法。`script_view` 对不存在的脚本继续抛出
`InvalidTaskSelection`，只用于显式查询；该错误不再参与写操作。
查询保留真实的 `None`、布尔值和整数，显示标签由客户端从这些值和菜单生成。
构造适配器时的模板对齐沿用原实现，本次不改 Config 生命周期。

后续 CLI 命令继续使用 `select_daily/enable_daily/select_weekly/start_weekly`。
需要回显时单独查询，分别报告写入结果与刷新失败。

回归测试对 GUI 原入口、AppService CLI 入口及 task_service 模块入口执行同一组输入和原生配置，
共同验证写入内容与顺序、返回值、空操作及异常语义。
