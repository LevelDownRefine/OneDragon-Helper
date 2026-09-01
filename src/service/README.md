# src/service — 服务层（AppService 组合根 + 平级 peer）

把 set_config、runner、链生成与校验内聚为统一薄接口，对 GUI 与 CLI 暴露同一套调用面。
从 src/gui/ 分离而出，无 Qt 依赖，故 GUI 与 CLI 共用同一实现，也便于无头测试。

## 设计定位

| 角色 | 说明 |
|------|------|
| 组合根，非协调器 peer | `AppService` 装配各 peer 并薄委托，是 GUI/CLI 唯一入口；各 peer 互不越界 |
| 平级 peer | ScriptService / DungeonService / WeeklyService / ChainService 互不拥有，由组合根装配 |
| 写盘路径 | config.yml→ScriptService；weekly_start.yml / weekly_timeouts.yml→WeeklyService；schedule.yml→schedule 模块函数 |
| 无 Qt 依赖 | 纯业务逻辑，不承载 UI 渲染（关机确认窗归 `src/gui/shutdown_dialog.py`） |

## 文件

| 模块 | 职责 |
|------|------|
| app_service.py | 组合根：装配 peer 并薄委托，GUI/CLI 唯一入口 |
| script_service.py | 单脚本配置：config.yml 完整读写（含条目增删改）+ get_script / build_script_entry / config_file_path |
| dungeon_service.py | 副本与周本声明只读（dungeon_list.yml / weekly_list.yml） |
| weekly_service.py | 周常运行期参数：weekly_start.yml（周几起）+ weekly_timeouts.yml（每周 7 格超时）读写与改名迁移 |
| chain_service.py | 链编排 peer：链生成、合法性校验、runner 命令构造、调度运行入口 |
| chain_gen.py | 脚本链配置生成：由 enabled_names + 子脚本 config 生成链配置并校验 |
| schedule.py | schedule.yml 读写（模块函数）+ ScheduledRun 调度运行编排 |
| run_actions.py | pre_run / post_run 各 step 的具体动作 |

## 依赖方向

```
launcher.py CLI  ┐
                 ├─▶ AppService（组合根）─┬─▶ ScriptService ─▶ WeeklyService（协作同步 weekly）
MainWindow  GUI  ┘                        ├─▶ DungeonService（副本 / 周本声明）
                                          ├─▶ WeeklyService（周常起始日 / 每周超时）
                                          └─▶ ChainService ─▶ chain_gen / schedule / utils_runner
```

调用方不感知 weekly 同步、链合法性校验、runner 命令构造等细节，全部内聚在 service/。

历史坑（已修）：`utils_shutdown.py` 曾内嵌 GUI 对话框类，致 `schedule → utils_shutdown →
gui.dialogs → app_service → chain_service → schedule` 成环，当时只能靠延迟 import 绕开。
现已把确认窗归位到 `src/gui/shutdown_dialog.py`，`utils_shutdown` 不再模块级依赖 GUI，环消除。
