# set_config — 副本配置适配器

统一 `set_config()` 适配器接口，内部封装各游戏脚本异构的 config 读写。各脚本的 config 格式、路径、字段名不同，由各 `ScriptConfig` 子类适配，上层 service 不感知差异。

> 设计定位：`set_config` 是适配器，把异构 config 适配成统一调用；不是外观模式，外观整合职责归组合根 `AppService`（编排 `src.service.chain_service` 与 `src.utils.utils_config` 等模块）。

> script_name 为全链路内部唯一标识，由 `get_script_name(script)` 获取，与进程名 `get_process_name` 区分。exe 脚本的 script_name 即进程名 basename 去后缀，如 `ok-ww`；python/bat 脚本文件的 script_name 即 display_name。注册表、`daily_task_list.yml`、`weekly_timeouts.yml` 的 key 全用 script_name，display_name 仅用于展示。config.yml 加载经 `check_script_name_uniqueness` 断言唯一。

## 架构

适配器 + 类层级，日常规则收敛在 `Daily` 对象上：

```
上层调用 ─▶ set_config(name, daily_display_name, task_name, sequence)  # 适配器接口
                │ 判空跳过 → 查 _CONFIGS 注册表 → 构造子类 → set_daily_task()
                ▼
          ScriptConfig，基类（周常文件 I/O：_load_weekly_config / _save_weekly_config）；
          日常文件 I/O 由 Daily 自持（_load_daily_config / _save_daily_config）
                │ _build_dailies 按声明 class 查注册表
   ┌──────┬──────────┬──────────┬──────┬──────┐
   ▼      ▼          ▼          ▼      ▼      ▼
 ok-ww  BetterGI/ok-ef OneDragon-Launcher/March7th-Launcher ok-nte  MAA
                │ 每个日常一个 Daily 实例（声明解析出落点）
                ▼
          src/config/daily.py：Daily / NoopDaily / Anomaly / MaaDaily
```

- 基类 `ScriptConfig` 只保留周常文件 I/O：`_load_weekly_config`（读路径容忍缺失返回 None；路径由各脚本显式声明 `_weekly_config_rel_path`，有 `_weekly_task_name` 即必须声明——注册期校验）/ `_save_weekly_config`（含保存后回读校验）/ `_init_config`（直调 utils_sub_config）/ `_is_aligned` / `set_daily_task` / `set_daily_enabled` / `_read_daily_tasks` / 周常三入口。
- **日常机制类**：`src/config/daily.py::Daily`——`__init__` 只做身份（`script_name` / `script_display_name` / `display_name` / `physical_name`）与配置路径（`config_rel_path` / `routine_rel_path`，全部来自声明 `config` / `routine` 字段），落点解析下沉为可覆写的 `_parse_landing`（模板方法）；公开 `_fields(task, sequence)`（该次选择的落点 {字段: 值}）、`update(task, sequence)`（取自己的段写入、返回是否有改动；段未落盘/config 缺失即 assert）、`read()`（反读，config 缺失/段未落盘 = 无真相）、`section` / `section_exists`（分段取段）、`read_enabled` / `set_enabled`（开关对）。文件 I/O 由 Daily 自持（直调 `utils_sub_config`，含保存后回读校验）：`_load_daily_config` / `_save_daily_config` / `_load_routine_config` / `_save_routine_config`——`update` / `read` / `set_enabled` 各自完成「读盘 → 改内存 → 有改动才落盘」的闭环，config dict 不在调用链上穿线。基类 `_parse_landing` 只解析**标准两层形态**；单层带 `key` 由 `AnomalyHunter`（`Anomaly` 子类）覆写，`NoopDaily` / `MaaDaily` 跳过通用解析——名字（`display_name`）只来自声明，全链路唯一来源。
- 机制类在 `daily.py`：`BgiDaily`（原神秘境资源筛选，读写沿用基类）、`NoopDaily`（绝区零/崩铁，上游自身已支持）、`Anomaly`（数据在自己段、开关在第二份文件）、`MaaDaily`（粥的 TaskQueue/StagePlan）、`MaaActivityDaily`（活动选项及过期检查）。适配器通过统一的 `_create_daily` 按声明构造日常。
- 子类声明 `_script_name`、`display_name` 与路径类属性：`_config_rel_path` 必填；声明了 `_game_path_keys` 则 `_game_config_rel_path` 必填；需模板初始化才设 `_template_rel_path`；`_backup_paths`（备份范围，目录或文件）必填；**机制类与文件路径由声明标注**（`daily_task_list.yml` 每个日常必填 `class`（`daily.py::DAILY_CLASSES` 注册表查表）与 `config`（该日常读写的主文件路径；`routine` 可选，日常开关文件））；`_build_dailies` 按声明逐个实例化并注入路径——加日常只改 yml，「主 config」概念不复存在。
- 注册表 `_CONFIGS: dict[str, type[ScriptConfig]]` 由 `@register` 装饰器显式填充，key 为 `_script_name`；路径声明不完整会在 import 时 assert 暴露。**注册表为模块私有，不对外 import**：外部只经模块级公开函数访问（`is_adapted` / `supports_weekly` / `get_config_path` / `get_game_exe_path` / `get_background_rel_path` / `iter_backup_paths` / `set_config` / `get_daily_readback` / `set_daily_enabled` / `set_weekly_task` / `get_weekly_task` / `set_weekly_start_day`）。

## 三个独立流程

| 流程 | 触发时机 | 作用 |
|------|----------|------|
| 初始化 init | 启动时 `config_workflow()` 调 `init_config_all()` | 确保脚本 config 与模板对齐，补全缺失结构 |
| 设置副本 set_daily_task | 外部调用 `set_config()` 时 | 按用户选择的副本/序列修改 config |
| 设置周常 prepare_weekly_start_day | 外部调用 `set_config()` 时 | 按周常起始日写周常开关，仅适配脚本支持 |

三者独立：初始化是防御性对齐，设置副本与周常是功能性响应。

## 落盘时机（何时调用 set_config）

子脚本 config 的落盘点按「能否在编辑期确定」分两类：

| 配置类型 | 落盘时机 | 说明 |
|----------|----------|------|
| 日常副本 / 序列（`task_name` / `sequence`） | **编辑期实时** | GUI 选副本（`TaskCardController.selectDaily`）、CLI `--task`/`--sequence` 覆盖，均直接调 `set_config` 实时写子脚本 config。无需等到运行全体。 |
| 周常副本（`set_weekly_task`） | **编辑期实时** | GUI 选周常副本（`selectWeekly`）直接写子脚本 config。 |
| 周常起始日（`weekly_start` → 周本开关） | **运行期** | 启用与否 = `today_weekday >= start_day`，只能在运行期按当天星期计算。故仅在 `generate_chain_config` 中经 `set_config(weekly_start=...)` 透传，由 `prepare_weekly_start_day` 写开关。 |

**关键结论**：除「按周几起决定开启/关闭」的周本开关必须在运行期落盘外，其余日常副本/序列、周常副本均在编辑期实时落盘子脚本 config。`generate_chain_config` 因此**不再重复写** task/sequence——它只负责把 `weekly_start` 透传给 `set_config`。

> 未选择（`task_name` 为空或「未选择」）保持 no-op：不清空、不触碰子脚本 config。这里不做「清空支持」，避免误删用户在他处的手动配置。

## 初始化流程 init

`ScriptConfig._init_config()`：仅对声明了 `_template_rel_path` 的脚本生效。先判模板是否存在（无模板直接返回），再直调 `load_config` 读当前 config（脚本未安装/未配置返回 None 时直接返回，不触碰 config），然后 `_load_template()` 加载模板 → 若 `_is_aligned` 一致则跳过；否则遍历模板字段 `safe_update(..., assert_key_exists=False)` 合并补全并保存。`_is_aligned` 递归比较，dict 递归、list 按索引、其余直接比。

落点（触发时机）：`config_workflow()` 在每次启动时调用 `init_config_all()`，遍历所有已注册脚本对齐 config 与模板。新增/修改脚本路径时（`add_script` / `update_script`）也调用 `init_config`。无 `_template_rel_path` 直接返回、`load_config` 缺失即返回——守卫确保无模板或脚本未安装时为空操作。反读适配器（`get_daily_readback` 等）一律不触发，保持纯只读。

| 脚本 | 当前调用 _init_config | 模板 | 说明 |
|------|---------------------|------|------|
| 鸣潮 | 是（no-op，无模板→直接返回） | — | 启动时自动触发，无模板时为空操作 |
| 原神 | 是 | `BGI一条龙.json` | 启动时自动触发，模板对齐补全缺失字段 |
| 终末地 | 是 | `okef一条龙.json` | 同上 |
| 绝区零 | 是 | `ZZZ一条龙.yml` | 同上 |
| 崩铁 | 是 | `M7A一条龙.yml` | 同上 |
| 异环 | 是（no-op，无模板→直接返回） | — | 同鸣潮 |
| 粥 | 补齐剿灭和三个入口、整理顺序、校验活动过期 | `gui.new.json` | 缺失任务使用 `MAA任务.json`；已有任务保留自身设置 |

## 设置副本流程 set_daily_task

### 任务声明

日常声明在 `config/daily_task_list.yml`，周常声明在 `config/weekly_task_list.yml`。
两份文件按脚本分组，组内使用相同的任务列表结构；文件区分日常、周常，不再声明 `type`。
用户的周几起、超时仍保存在 `weekly.yml`。

- `display_name` 是展示名，也是**声明层主键**（日常/选项的匹配、映射全按展示名）；`physical_name` 是写入原生配置的值，省略时使用展示名。
- `options` 是选项组；`key` 指定写入的原生字段，`values` 列举选项，或以 `source` 从本机脚本资源读取选项。
- `source.path` 指定资源文件，`source.key` 用列表声明逐层字典键路径（如终末地 `[stages_dict, 干员养成]`、崩铁 `[历战余响]`），省略或 `[]` 读取根节点。基类统一返回末层列表的字符串或字典的键，保留资源顺序，取值不依赖任务展示名或物理名。
- 原神暂保留 `source.category`，由原神适配器筛选 `points` 中对应 `type` 的名称；不能与 `source.key` 同时声明。
- 每个选项可继续包含 `options`（递归声明）。
- 顶层任务 `key` 供对应子类的周常操作使用（开关、列表字段或起始日字段）。

`task_config.py` 只读取、校验声明（`get_daily_configs` 返回某脚本全部日常声明，按展示名匹配）；`daily.py` 的 `Daily` 把声明解析成落点；`daily_config.py` 把声明**物化**成 GUI 菜单。

### 写路径

`set_daily_task(daily_display_name, task_name, sequence)`：

1. `assert daily_display_name`——**恒非空**：单日常脚本也要给（界面逐行渲染，一行即一个日常，该行行名就是它），不存在「单日常省掉」或「适配器补名」的形态。
2. `_dispatch_daily(daily_display_name)` 按展示名取日常对象（声明没有即 assert）。
3. `daily.update(task_name, sequence)`——自身完成「读 config → 写数据段 → 有改动才落盘」：段存在性/config 在场由 `update` 内部断言（段缺失时 `section` 返回游离 dict，直接写会静默丢失）。
4. 顺带 `set_daily_enabled(daily, True)`——`Daily.set_enabled` 默认不做事，只有 `Anomaly` 真实写自己那条 Routine Item；该脚本无日常开关文件时 `set_daily_enabled` 直接跳过（选择即启用）。

> 两个「默认不做事」让类型检查消失：无需适配的日常（绝区零/崩铁）由 `NoopDaily` 覆写 `update` 恒返回 False（读盘一次但不落盘）；无开关机制的日常由基类 `set_enabled` 兜底——标志位（no_op / enable_on_select）都不存在。

> 写盘校验：落盘点（Daily 的 `_save_daily_config` / `_save_routine_config`、ScriptConfig 的 `_save_weekly_config`、`_init_config`）写后都重读并与预期整段相等断言。save_config 为同步阻塞写，重读必为新内容，无需 sleep。校验失败属不该发生，用 assert。

### 菜单（GUI 直吃声明词汇）

`daily_config.get_daily_map()` 把声明**物化**成菜单：词汇与声明一致（`display_name` / `physical_name` / 递归 `options.values`），只做两件事——`source` 引用替换为本机资源展开的具体副本；补齐省略的 `physical_name`（回落展示名）。不做改名与拍平。

日常资源选项由 `Daily.get_task_lists(source)` 持有。菜单把完整日常声明与当前选项的 `source` 交给 `ScriptConfig.get_task_lists(declaration, source)`；适配器只统一构造并委托，不按脚本覆写或反查日常声明。`BgiDaily` 筛选秘境分类，`MaaActivityDaily` 直接使用自己的配置路径确定客户端。通用 `path / key` 读取放在 `task_source.read_task_source`，供 `Daily` 基类和周常菜单共用。读取菜单不触发配置初始化或写盘。

- **单层带 `key` 的日常**（追猎目标）物化时**整组即唯一一级项**（展示名用日常名）、values 作二级——这是写路径语义（`_fields` 要求一级项名=日常名、值走二级），不能拆散。
- 单层无 `key` 的日常（no-op）values 即一级项；两层日常各 value 作一级项。
- 「最多两级」assert 留在物化层（QML 目前渲染两级，不许静默丢层）；QML 级联化后删除。
- 菜单**不经过 `ScriptConfig`**：声明里新增一个日常时菜单照常显示；实例化没跟上（`_build_dailies` 没建它）时 `_dispatch_daily` 找不到、当场报错。

GUI 侧两条流互不依赖，靠声明 `display_name` 对齐：菜单流（`get_daily_map`，启动缓存一次）回答「能选什么」；反读流（`get_daily_readback`，每次求值）回答「已经选了什么」；chip 无真相时回退菜单首个选项。

### 反读

`_read_daily_tasks()` 逐日常调 `daily.read()` + `daily.read_enabled()`（各自读自己那份文件），每项一条记录 `{name, task, sequence, enabled}`（facade `get_daily_readback`），顺序与声明一致。反读不看启用状态影响副本（用于呈现未启用的日常）。

**未安装 = 无真相**：脚本未安装（config 缺失）或开关文件缺失时对应字段为 None，不谎报「已停用」；无日常开关文件的脚本开关恒为 None，界面据此不提供「不启用」。config 损坏或字段值未知属异常，`Daily.read` 内 assert 暴露，不静默回退。

### 各脚本策略

| 脚本 | 声明 `class` | 说明 |
|------|------------------------|------|
| 鸣潮 / 原神 / 终末地 | `Daily` | 落点全由声明给出；原神/终末地两级共用一级字段（`_single_field`：二级覆盖一级，读时不做一级映射） |
| 绝区零 / 崩铁 | `NoopDaily` | 无需适配副本选择（跳过通用解析） |
| 异环 | `Anomaly` + `AnomalyHunter` | 两个日常各一段、各一个类，见下节 |
| 粥 | `MaaDaily` | TaskQueue / StagePlan（跳过通用解析），见下节 |

### 异环：两个日常各自独立启用

异环日常玩法两类：异象界域在 `DailyRoutineTaskConfigs.json` 的 `daily_anomaly` 段，追猎目标在 `daily_anomaly_hunter` 段（段名 = 日常物理名，`Anomaly.section` 取段）。开关写在 `DailyRoutineTask.json` 的 `Routine Items`，`id` 为 `daily_anomaly`/`daily_anomaly_hunter` 的 `enabled`。

`Anomaly` 提供共同实现（取段 + 开关读写，解析走基类两层形态）；追猎目标单层带 `key`，由 `AnomalyHunter` 覆写解析与反读。选副本后顺带启用该日常的 Routine Item（`set_daily_task` 无条件经 `set_daily_enabled`），**另一个日常不动**——工具层不再做互斥，两个日常可同时启用（是否只跑一个由游戏侧决定）。「不启用」走 `set_daily_enabled(daily, enabled)`：读开关文件 → `daily.set_enabled`（只动开关、不动副本选择）→ 有改动才落盘。

「日常展示名 → 物理名」（段名 / routine item id）的唯一换算点是 `Daily.physical_name`——来自声明，构造时解析；展示名在这些文件里不存在，故没有独立换算函数。

### 粥：TaskQueue / StagePlan

`MaaDaily` 按声明物理名绑定一个原生 `FightTask`，理智作战与剩余理智分别选择一个关卡、独立启停；`MaaActivityDaily` 增加本地活动资源读取与初始化过期检查。新任务从随项目发布的 `MAA任务.json` 创建，不借用其他任务。`ArknightsConfig._init_config` 安排必刷剿灭和三个入口、清理额外 Fight，保留非战斗项。实际执行及关卡开放判断由 MAA 负责，字段依据和完整行为见 [MAA 原生刷图适配](../../docs/maa-adapter.md)。

## 设置周常流程 prepare_weekly_start_day

`prepare_weekly_start_day(start_day)` 是周常开关的唯一写入入口，无中间钩子：先 `_check_weekly_start(start_day)` 校验（未声明 `_weekly_task_name` 即 assert 未适配；`start_day` 必须在 1~7），再由各子类按自身 config 结构落盘。基类只兜底 assert——声明了 `_weekly_task_name` 的子类必须覆写，由 `register` 在 import 期校验。

各脚本落点：

| 脚本 | 落点 |
|------|------|
| 鸣潮 | `Additional Tasks to Run After Daily Task` 列表增删 `Check Weekly Garden` |
| 终末地 | `DailyTask.json` 的「只买不卖」布尔（语义反相） |
| OneDragon-Launcher | `_group.yml` 的 `app_list` 中 `lost_void.enabled` |
| 崩铁 | `config.yaml` 的 `currencywars_enable`（按周几起门控）+ `echo_of_war_start_day_of_week`（字面起始日，交 M7A 自行门控） |
| 明日方舟（MAA） | 所有 FightTask 临期药常开，`MedicineExpireDays = 8 - 周几起`；运行前只同步窗口及兜底开关 |

前四个用 `is_weekly_start_reached(start_day)` 得出「今天是否已到起始日」再写开关；MAA 不经过该门控。

> 与编辑期的 `set_weekly_start_day`（崩铁 / MAA 覆写，只落盘字面起始日、不动开关）分层：`prepare_weekly_start_day` 是运行期入口，`set_weekly_start_day` 是编辑期入口。

声明 `_weekly_task_name` 的脚本：ok-ww、ok-ef、OneDragon-Launcher、March7th-Launcher、明日方舟（MAA）；其余脚本调用即断言失败。

## 安全字段更新 safe_update

`src/utils/utils_dict.py` 提供 `safe_update(config, key, value, display_name="", assert_key_exists=True) -> bool` 与 `get_field`（`Daily` 与 `ScriptConfig` 共用，独立成模块避免循环导入）：

- `assert_key_exists=True`：断言 `key in config`，并按 `_scalar_kind` 归一化做类型一致比较（容忍 ruamel 的 str 子类、区分 bool/int）；值不同才写，返回是否修改。
- `False`：允许新增 key，缺失时 warning 并写入，返回 True。
- 是所有字段写入统一入口，避免散落的 `.get()` 或直接赋值。

## 外部接口

```python
from src.config.set_config import set_config

set_config("ok-ww", daily_display_name="每日任务", task_name="无音区")  # 无二级
set_config("ok-ww", daily_display_name="每日任务", task_name="模拟领域", sequence="贝币")  # 二级传物理值
set_config("ok-nte", daily_display_name="异象界域", task_name="空幕", sequence=6)
set_config("ok-ww", weekly_start=3)  # 周常起始日，仅适配脚本生效
set_config("ok-ww", task_name=None)  # 跳过
set_config("ok-ww", task_name="未选择")  # 跳过
```

`iter_backup_paths()` 返回 {script_name: 备份路径元组}——「该脚本的配置面在哪」的唯一声明处，供配置备份与恢复遍历。元素是**目录**（整目录递归打包）或**文件**（单文件收录），相对脚本根目录。仅用于收集文件，不解析或校验配置内容。

> 与读写路径（``_config_rel_path`` 等）刻意解耦：读写关心「哪个文件的哪个字段」，备份关心「配置面在哪」。声明了 ``_backup_paths`` 即表示该脚本要备份的配置全在这些路径里，备份层按条展开，不再回头拼读写路径。整目录形态用目录（ok-ww/ok-ef/ok-nte 的 ``working/configs``、BetterGI 的 ``User``、绝区零与粥的 ``config``），散装形态用文件（崩铁只要根目录 ``config.yaml``，其 ``config/`` 仅剩 workflows 故不声明）。

`set_config()` 接收 script_name；python/bat 脚本文件不在注册表内时优雅跳过。每次调用实例化对应子类并触发初始化；`weekly_start` 非 None 才写周常。

## 相关文件

| 文件 | 作用 |
|------|------|
| `set_config.py` | 本适配器，适配器接口 + 类层级；各脚本路径由子类声明，`@register` 显式注册；各日常脚本子类定义在各自 config 旁 |
| `daily.py` | 日常规则对象：`Daily` 基类（声明 → 落点 + 读写规则）与机制类 `NoopDaily` / `Anomaly` / `MaaDaily`；纯规则不碰盘 |
| `task_config.py` | 两份任务声明的读取、校验、物理名/取值映射 |
| `daily_config.py` | 把声明**物化**成 GUI 菜单（source 展开 + 补缺省物理名），词汇与声明一致 |
| `src/utils/utils_dict.py` | `safe_update` / `get_field` 字段工具（`Daily` 与 `ScriptConfig` 共用） |
| `src/link.py` | 游戏/脚本链接集中管理（官网、B 站、GitHub、banner 下载）；与 config 适配解耦。沿用基类 `GameLink` + 各脚本子类继承结构，`@register` 注册到 `_LINKS`，key 为 `_script_name`；本地背景图路径（`background`）仍声明在 set_config 子类，经 `_CONFIGS` 读取 |
| `config/daily_task_list.yml` | 各脚本支持的副本及序列展示名，key 为 script_name |
| `config/BGI一条龙.json` 等 | 各脚本 init 模板（粥无模板） |

## 如何新增一个游戏适配

1. `set_config.py` 新建子类继承 `ScriptConfig` 并加 `@register`：设 `_script_name`、`display_name` 与路径类属性 `_config_rel_path` 必填、`_game_config_rel_path` 声明 `_game_path_keys` 时必填；需模板初始化才设 `_template_rel_path`。
2. 在 `daily_task_list.yml` 给日常标注 `class`（机制类名，注册表见 `daily.py::DAILY_CLASSES`）：标准两层 `Daily`；分段 `Anomaly`（追猎目标 `AnomalyHunter`）/TaskQueue `MaaDaily`/无需适配 `NoopDaily`；config 子类零改动；声明表达不了的特殊读写才覆写 `update` / `read`。
3. `config/daily_task_list.yml` 加该脚本的日常声明（key 用 script_name）；菜单自动出现，无需改 GUI。
4. `_init_config` 已在启动时自动触发；无 `_template_rel_path` 时为空操作。
5. 补测试 `tests/test_set_config_subclasses.py`（可参照 golden：`PYTHONPATH=src python -m tests.test_golden_daily` 重新生成基线）。

## 设计原则

- 两流程分离：初始化对齐模板与设置副本响应选择独立，不混。
- 声明即真相：落点能从 `daily_task_list.yml` 推导的在 `Daily` 里解析，子类只声明声明层表达不了的东西（脚本内路径、文件内键名）；菜单是同一份声明的物化，加日常只改 yml。
- 机制类脚本级：一份声明一个实例，名字只来自声明（`name`）；形状与机制的正交差异（如异环两个日常一两层一单层）由机制类自己解析。
- 严格 assert：配置不一致立即报错，不静默容忍。字典访问先 assert key 再直接访问，不用 `.get()`。
- 类型一致：sequence 类型由 `daily_task_list.yml` 的 physical_name 决定，不把数字转为字符串。
- 未安装 = 无真相：反读缺失字段返回 None，不谎报「已停用」；损坏/未知值 assert 暴露。

`get_game_path_keys(script_name, rel)` 复用打开游戏所用的路径声明，供恢复保留本机游戏路径；其他文件返回空元组。
