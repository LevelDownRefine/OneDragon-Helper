# src/service — 服务层（AppService 组合根 + 平级 peer）

把 set_config、runner、链生成与校验内聚为统一薄接口，对 GUI 与 CLI 暴露同一套调用面。
从 src/gui/ 分离而出，无 Qt 依赖，故 GUI 与 CLI 共用同一实现，也便于无头测试。

## 设计定位

| 角色 | 说明 |
|------|------|
| 组合根，非协调器 peer | `AppService` 装配各 peer 并薄委托，是 GUI/CLI 唯一入口；各 peer 互不越界 |
| 平级 peer | 单脚本配置（src.utils.utils_config）/ chain_service（链编排）互不拥有，由组合根装配 |
| 周常运行期参数 | `weekly.yml` 的 `weekly_start` 段（周几起，条目级 `{脚本: {周常: 0 | 1~7}}`，0 = 不启用）与 `weekly_timeouts` 段的读写归 `src.utils.utils_weekly` 模块函数（无状态、无 peer 实例）；周常落点归 `src.config.weekly`；schedule.yml 归 schedule 模块函数 |
| 无 Qt 依赖 | 纯业务逻辑，不承载 UI 渲染（关机确认窗归 `src/gui/shutdown_dialog.py`） |

## 文件

| 模块 | 职责 |
|------|------|
| app_service.py | 组合根：装配 peer 并薄委托，GUI/CLI 唯一入口 |
| task_service.py | 无 Qt CLI 的脚本列表/任务卡聚合查询、日常选择校验与写后反读 |
| utils_config.py | 单脚本配置（原 script_service.py 已退化为模块函数）：config.yml 完整读写（含条目增删改）+ get_script / build_script_entry / config_file_path |
| chain_service.py | 链编排 peer：链生成、合法性校验、runner 命令构造、调度运行入口 |
| chain_gen.py | 脚本链配置生成：由 enabled_names + 子脚本 config 生成链配置并校验 |
| schedule.py | schedule.yml 读写（StartupOptions 自动启动开关/秒数、RunOptions 运行选项）+ ScheduledRun 调度运行编排 |
| daily_plan.py | 每日计划读写与 Windows 原生任务注册，并可回读任务实际状态；系统仅保存触发时间和 --run-daily 入口 |
| backup_service.py | 配置备份与恢复：普通 ZIP 收集与恢复；按当前脚本目录覆盖，保留游戏路径，未配置脚本跳过 |
| run_actions.py | pre_run / post_run 各 step 的具体动作 |

## 手动更新

`AppService` 装配 `src.update.service.UpdateService`，薄委托本地状态读取、检查、下载和安装交接。
更新协议、运行锁、安装事务和独立更新器集中在 [src/update](../update/README.md)，无 Qt 依赖。
GUI 的弹窗和工作线程保留在 `src/gui`，经 AppService 调用更新服务。

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
                 ├─▶ AppService（组合根）─┬─▶ src.utils.utils_config（单脚本配置）─▶ src.utils.utils_weekly（协作同步 weekly）
MainWindow  GUI  ┘                        ├─▶ daily_config 模块函数（副本 / 周本声明，src.config）
                                          └─▶ chain_service ─▶ chain_gen / schedule / utils_runner
                                                  └─▶ src.utils.utils_weekly（周常参数读写）
```

调用方不感知 weekly 同步、链合法性校验、runner 命令构造等细节，全部内聚在 service/。

无 Qt 入口 `python -m src.headless` 经 AppService 访问 task_service，提供一次性 `call`
与持久 `serve --stdio`；开放 `app.snapshot/script.view`、`daily.select/enable`、
`weekly.select/start`，供现有 GUI 的 `--cli-backend` 测试模式使用。
请求、返回结构与生命周期见 [CLI 协议](../../docs/rust-feasibility/headless-cli.md)。

`utils_shutdown.py` 不得模块级依赖 GUI 层：否则 `schedule → utils_shutdown →
gui.dialogs → app_service → chain_service → schedule` 成环，确认窗实现于 `src/gui/shutdown_dialog.py`，`utils_shutdown` 仅延迟 import 它。

## 每日运行

在配置弹窗启用每日计划时注册当前用户的 Windows 交互任务（需管理员权限），仅记录程序入口和每日时间。计划默认关闭，默认时间为 04:10，对所有脚本生效。GUI 关闭仍会按时触发，电脑需保持开机并登录；不唤醒、不补跑错过的时间。

`--run-daily` 每次读取 daily_run（含独立 run_options 块），以 now 运行当天全部脚本的链；手动脚本 enabled 不参与筛选，运行选项也取每日计划独立配置（不再回落手动 RunOptions）。计划已关闭或没有可运行的脚本则无动作。只改副本、超时或运行选项无需更新系统任务，修改时间或开关才更新任务；暂停保留时间。旧 CLI `--schedule-run HH:MM[:SS]` 保留一次性等待用途（可带秒，便于精确等待或集成测试用「当前 + 几秒」）。

系统任务按安装目录和用户命名。请保持安装目录和可执行文件路径稳定；移动安装前先关闭旧计划，再在新位置启用。任务更新成功才写配置，写入失败时恢复原任务。
