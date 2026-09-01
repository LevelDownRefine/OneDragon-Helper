# set_config — 副本配置适配器

统一 `set_config()` 适配器接口，内部封装各游戏脚本异构的 config 读写。各脚本的 config 格式、路径、字段名不同，由各 `ScriptConfig` 子类适配，上层 service 不感知差异。

> 设计定位：`set_config` 是适配器，把异构 config 适配成统一调用；不是外观模式，外观整合职责归 `src/service/` 的 ChainService。

> script_name 为全链路内部唯一标识，由 `get_script_name(script)` 获取，与进程名 `get_process_name` 区分。exe 脚本的 script_name 即进程名 basename 去后缀，如 `ok-ww`；python/bat 脚本文件的 script_name 即 display_name。注册表、`dungeon_list.yml`、`weekly_timeouts.yml` 的 key 全用 script_name，display_name 仅用于展示。config.yml 加载经 `check_script_name_uniqueness` 断言唯一。

## 架构

适配器 + 类层级，非模板方法：

```
上层调用 ─▶ set_config(name, dungeon_name, sequence)  # 适配器接口，name=脚本唯一标识
                │ 判空跳过 → 查 _CONFIGS 注册表 → 构造子类 → set_dungeon()
                ▼
          ScriptConfig，基类
                │ 继承
   ┌──────┬──────────┬──────────┬──────┬──────┐
   ▼      ▼          ▼          ▼      ▼      ▼
 ok-ww  BetterGI/ok-ef OneDragon-Launcher/March7th-Assistant ok-nte  MAA
```

- 基类 `ScriptConfig` 提供通用能力：`_load` / `_save` / `_verify_saved` / `_update_task`（含二级序列）/ `_init_config` / `_is_aligned` / `set_dungeon` / `safe_update`。
- 子类声明 `_script_name`、`display_name` 与路径类属性：`_config_rel_path` 必填；声明了 `_game_path_keys` 则 `_game_config_rel_path` 必填；需模板初始化才设 `_template_rel_path`。`_task_key` / `_task_map` 按需覆盖。
- 注册表 `_CONFIGS: dict[str, type[ScriptConfig]]` 由 `@register` 装饰器显式填充，key 为 `_script_name`；路径声明不完整会在 import 时 assert 暴露。**注册表为模块私有，不对外 import**：外部只经模块级公开函数访问（`is_adapted` / `supports_weekly` / `get_config_path` / `get_game_exe_path` / `get_background_rel_path` / `set_config` / `set_weekly_dungeon`）。

## 三个独立流程

| 流程 | 触发时机 | 作用 |
|------|----------|------|
| 初始化 init | 已就绪但未接入任何触发点（调用时机待 review 定） | 确保脚本 config 与模板对齐，补全缺失结构 |
| 设置副本 set_dungeon | 外部调用 `set_config()` 时 | 按用户选择的副本/序列修改 config |
| 设置周常 set_weekly | 外部调用 `set_config()` 时 | 按周常起始日写周常开关，仅适配脚本支持 |

三者独立：初始化是防御性对齐，设置副本与周常是功能性响应。

## 落盘时机（何时调用 set_config）

子脚本 config 的落盘点按「能否在编辑期确定」分两类：

| 配置类型 | 落盘时机 | 说明 |
|----------|----------|------|
| 日常副本 / 序列（`dungeon_name` / `sequence`） | **编辑期实时** | GUI 选副本（`TaskCardController.selectDungeon`）、CLI `--dungeon`/`--sequence` 覆盖，均直接调 `set_config` 实时写子脚本 config。无需等到运行全体。 |
| 周常副本（`set_weekly_dungeon`） | **编辑期实时** | GUI 选周常副本（`selectWeeklyDungeon`）直接写子脚本 config。 |
| 周常起始日（`weekly_start` → 周本开关） | **运行期** | 启用与否 = `today_weekday >= start_day`，只能在运行期按当天星期计算。故仅在 `generate_chain_config` 中经 `set_config(weekly_start=...)` 透传，由 `set_weekly` 写开关。 |

**关键结论**：除「按周几起决定开启/关闭」的周本开关必须在运行期落盘外，其余日常副本/序列、周常副本均在编辑期实时落盘子脚本 config。`generate_chain_config` 因此**不再重复写** dungeon/sequence——它只负责把 `weekly_start` 透传给 `set_config`。

> 未选择（`dungeon_name` 为空或「未选择」）保持 no-op：不清空、不触碰子脚本 config。这里不做「清空支持」，避免误删用户在他处的手动配置。

> 历史包袱：早期子脚本 config 唯一的写盘点是「运行全体」时 `generate_chain_config` 内的 `set_config` 循环，导致编辑期改副本要等运行全体才生效。现改为编辑期实时落盘，运行全体路径不再负责 dungeon/sequence 落盘（仅周本开关）。

## 初始化流程 init

`ScriptConfig._init_config()`：仅对声明了 `_template_rel_path` 的脚本生效。先判模板是否存在（无模板直接返回），再 `self._load(allow_missing=True)` 读当前 config（脚本未安装/未配置返回 None 时直接返回，不触碰 config），然后 `_load_template()` 加载模板 → 若 `_is_aligned` 一致则跳过；否则遍历模板字段 `safe_update(..., assert_key_exists=False)` 合并补全并保存。`_is_aligned` 递归比较，dict 递归、list 按索引、其余直接比。

落点（触发时机）：`config_workflow()` 在每次启动时调用 `init_config_all()`，遍历所有已注册脚本对齐 config 与模板。新增/修改脚本路径时（`add_script` / `update_script`）也调用 `init_config`。无 `_template_rel_path` 直接返回、`self._load(allow_missing=True)` 缺失返回——守卫确保无模板或脚本未安装时为空操作。反读适配器（`get_dungeon` 等）一律不触发，保持纯只读。

| 脚本 | 当前调用 _init_config | 模板 | 说明 |
|------|---------------------|------|------|
| 鸣潮 | 是（no-op，无模板→直接返回） | — | 启动时自动触发，无模板时为空操作 |
| 原神 | 是 | `BGI一条龙.json` | 启动时自动触发，模板对齐补全缺失字段 |
| 终末地 | 是 | `okef一条龙.json` | 同上 |
| 绝区零 | 是 | `ZZZ一条龙.yml` | 同上 |
| 崩铁 | 是 | `M7A一条龙.yml` | 同上 |
| 异环 | 是（no-op，无模板→直接返回） | — | 同鸣潮 |
| 粥 | no-op（无模板） | — | `_task_map` 固化为类属性（不再加载模板；原 `MAA一条龙.json` 模板已删除）|

## 设置副本流程 set_dungeon

基类模板流程：`_load()` → `_update_task(config, dungeon_name, sequence)`（含二级序列）→ 有改动则 `_save()`，保存后 `_verify_saved()` 重读校验落盘一致性。

> 写盘校验：`_save()` 是唯一落盘点，写后 `_verify_saved()` 重读并与预期整段相等断言。save_config 为同步阻塞写，重读必为新内容，无需 sleep。校验失败属不该发生，用 assert。

| 钩子 | 作用 | 默认 |
|------|------|------|
| `_update_task(config, dungeon_name, sequence)` | 更新副本类型字段与二级序列 | 设 `_task_key` 即启用，用 `_task_map` 映射，空 map 用 `dungeon_name` 原值；sequence 非 None 即 assert（基类无二级序列通道） |

各脚本策略：

| 脚本 | 覆盖 set_dungeon | _task_key | 覆盖 _update_task | 说明 |
|------|-------------------|-------------|------------------------|------|
| 鸣潮 | 否 | `Which to Farm` | 是 | 经 `super()._update_task(config, dungeon_name, None)` 复用副本写入，再按 `_sequence_map` 写序列；模拟领域需映射值，凝素/无音区直接用 sequence |
| 原神 | 否 | `DomainName` | 否 | — |
| 终末地 | 否 | `体力本` | 否 | — |
| 崩铁 | 否 | — | 否 | 日常无需适配（set_dungeon 为 no-op，上游自身已支持），chip 呈现声明项 |
| 异环 | 否，覆盖做互斥切换 | `任务类型`（声明于 `_mode_specs`） | 是 | 完全自定义（不调 super）：副本→模式经 `_dungeon_to_mode` 反查 `_mode_specs` 声明式映射（含 `task_field`+`seq_fields`）；`DailyRoutineTask.json` 切换 `daily_anomaly`↔`daily_anomaly_hunter` 互斥启用，复用基类 `_load`/`_save`，仅路径 `_routine_config_rel_path` 不同 |
| 绝区零 | 是，空实现仅 print | — | — | 无需适配副本选择（上游自身已支持） |
| 粥 | 是，完全自定义 | — | 是 | 操作 `TaskQueue` 禁用全部→启用剿灭+选定+土，不写二级序列 |

标准流程：不覆盖 set_dungeon，靠 `_task_key` 适配；需二级序列支持则覆盖 `_update_task`（在 `super()._update_task(config, dungeon_name, None)` 后补序列）；需完全自定义如粥或无需适配如绝区零才覆盖 set_dungeon。

### 异环：追猎目标与异象界域互斥

异环日常玩法两类互斥：异象界域在 `DailyRoutineTaskConfigs.json` 的 `daily_anomaly` 段，追猎目标在 `daily_anomaly_hunter` 段。互斥开关写在 `DailyRoutineTask.json` 的 `Routine Items`，`id` 为 `daily_anomaly`/`daily_anomaly_hunter` 的 `enabled`。

NTEConfig 覆盖 `set_dungeon`：选空幕等异象界域副本 → 写 `daily_anomaly` 的 `任务类型`+序号，启用 `daily_anomaly`、停用 `daily_anomaly_hunter`；选追猎目标并选 boss → 在 `daily_anomaly_hunter` 写 `追猎目标`，启用 `daily_anomaly_hunter`、停用 `daily_anomaly`。

NTEConfig 覆盖 `set_dungeon`：按 `_dungeon_to_mode` 反查所选副本所属模式（`daily_anomaly` / `daily_anomaly_hunter`），委托基类写第一份文件（经 `_mode_specs` 声明式字段映射写入 `任务类型`+序号或 `追猎目标`），自身再切换第二份互斥文件 `DailyRoutineTask.json` 的 Routine Item 启用状态。相关路径/常量在 `NTEConfig`：`_routine_config_rel_path`、`_exclusive_routine_items`、`_anomaly_seq_key_map`、`_mode_specs`、`_dungeon_to_mode`。

## 设置周常流程 set_weekly

`set_weekly(start_day)`：`enabled=False` 短路；`assert` 脚本声明了 `_weekly_task_name` 且 `start_day` 在 1~7，再写开关。

多数脚本经 `_write_weekly(is_weekly_start_reached(start_day))` 写二值开关（周几起决定今天是否启用）。明日方舟（MAA）覆写 `set_weekly`：不按「今天是否到起始日」门控，每次调用直接写 `gui.new.json`——开启的 FightTask 设 `UseExpiringMedicine=true`（其余 false），`MedicineExpireDays` 由周几起推算（周几起 = 7 - MedicineExpireDays + 1）。

声明 `_weekly_task_name` 的脚本：ok-ww、OneDragon-Launcher、March7th-Assistant、ok-ef、崩铁、绝区零、明日方舟（MAA）；其余脚本调用即断言失败。

## 安全字段更新 safe_update

`safe_update(config, key, value, display_name="", assert_key_exists=True) -> bool`：

- `assert_key_exists=True`：断言 `key in config`，并 `assert type(config[key]) is type(value)` 严格类型比较，避免 bool/int 混淆；值不同才写，返回是否修改。
- `False`：允许新增 key，缺失时 print 并写入，返回 True。
- 是所有字段写入统一入口，避免散落的 `.get()` 或直接赋值。

## 外部接口

```python
from src.config.set_config import set_config

set_config("ok-ww", dungeon_name="无音区")                         # 无序列
set_config("ok-ww", dungeon_name="凝素领域", sequence=17)          # 序列为数字
set_config("ok-ww", dungeon_name="模拟领域", sequence="贝币")       # 序列为字符串
set_config("ok-ww", weekly_start=3)                                # 周常起始日，仅适配脚本生效
set_config("ok-ww", dungeon_name=None)                             # 跳过
set_config("ok-ww", dungeon_name="未选择")                         # 跳过
```

`set_config()` 接收 script_name；python/bat 脚本文件不在注册表内时优雅跳过。每次调用实例化对应子类并触发初始化；`weekly_start` 非 None 才写周常。

## 相关文件

| 文件 | 作用 |
|------|------|
| `set_config.py` | 本适配器，适配器接口 + 类层级；各脚本路径由子类声明，`@register` 显式注册 |
| `subscript.py` | config 读写基础设施，`get_script_name` / `load` / `save` / `load_template`，只接收 `rel_path`，不感知具体脚本 |
| `dungeon_config.py` | `dungeon_list.yml` 解析 |
| `src/link.py` | 游戏/脚本链接集中管理（官网、B 站、GitHub、banner 下载）；与 config 适配解耦。沿用基类 `GameLink` + 各脚本子类（`WutheringWavesLink`/`GenshinLink` 等）继承结构，`@register` 注册到 `_LINKS`，key 为 `_script_name`；本地背景图路径（`background`）仍声明在 set_config 子类，经 `_CONFIGS` 读取 |
| `config/dungeon_list.yml` | 各脚本支持的副本及序列展示名，key 为 script_name |
| `config/BGI一条龙.json` 等 | 各脚本 init 模板（粥无模板，`_task_map` 固化类属性）|

## 如何新增一个游戏适配

1. `set_config.py` 新建子类继承 `ScriptConfig` 并加 `@register`：设 `_script_name`、`display_name` 与路径类属性 `_config_rel_path` 必填、`_game_config_rel_path` 声明 `_game_path_keys` 时必填；需模板初始化才设 `_template_rel_path`，且 `_task_map` 优先固化为类属性（避免反读/写路径依赖模板加载）。
2. 设 `_task_key` / `_task_map`，需序列支持则覆盖 `_update_task`（在 `super()._update_task(config, dungeon_name, None)` 后补序列），标准流程不够则覆盖 `set_dungeon`；`_init_config` 已在启动时自动触发，新增脚本无需显式调用；无 `_template_rel_path` 时为空操作。
3. `config/dungeon_list.yml` 加副本/序列选项，key 用 script_name。
4. 补测试 `tests/test_set_config_subclasses.py`。

## 设计原则

- 两流程分离：初始化对齐模板与设置副本响应选择独立，不混。
- 克制：无明确收益不抽抽象。异环多副本共用的映射才抽 `_mode_specs`/`_dungeon_to_mode` 声明式表，鸣潮单副本不抽。
- 严格 assert：配置不一致立即报错，不静默容忍。字典访问先 assert key 再直接访问，不用 `.get()`。
- 类型一致：sequence 类型由 `dungeon_list.yml` 的 value 决定，不做额外转换。
