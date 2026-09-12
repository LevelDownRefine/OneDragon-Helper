# set_config — 副本配置适配器

统一 `set_config()` 适配器接口，内部封装各游戏脚本异构的 config 读写。各脚本的 config 格式、路径、字段名不同，由各 `ScriptConfig` 子类适配，上层 service 不感知差异。

> 设计定位：`set_config` 是适配器，把异构 config 适配成统一调用；不是外观模式，外观整合职责归组合根 `AppService`（编排 `src.service.chain_service` 与 `src.utils.utils_config` 等模块）。

> script_name 为全链路内部唯一标识，由 `get_script_name(script)` 获取，与进程名 `get_process_name` 区分。exe 脚本的 script_name 即进程名 basename 去后缀，如 `ok-ww`；python/bat 脚本文件的 script_name 即 display_name。注册表、`task_list.yml`、`weekly.yml` 的 key 全用 script_name，display_name 仅用于展示。config.yml 加载经 `check_script_name_uniqueness` 断言唯一。

## 架构

适配器 + 类层级，非模板方法：

```
上层调用 ─▶ set_config(name, option_name, sequence, daily_name=...)  # 适配器接口，name=脚本唯一标识
                │ 判空跳过 → 查 _CONFIGS 注册表 → 构造子类 → set_daily_task(daily_name, ...)
                ▼
          ScriptConfig，基类
                │ 继承
   ┌──────┬──────────┬──────────┬──────┬──────┐
   ▼      ▼          ▼          ▼      ▼      ▼
 ok-ww  BetterGI/ok-ef OneDragon-Launcher/March7th-Launcher ok-nte  MAA
```

- 基类 `ScriptConfig` 提供通用能力：`_load` / `_save` / `_verify_saved` / `_update_daily_task`（含二级序列）/ `_init_config` / `_is_aligned` / `set_daily_task` / `safe_update`。
- 子类声明 `_script_name`、`display_name` 与路径类属性：`_config_rel_path` 必填；声明了 `_game_path_keys` 则 `_game_config_rel_path` 必填；需模板初始化才设 `_template_rel_path`；`_backup_paths`（备份范围，目录或文件）必填。具名日常、周常的字段绑定和选项由 `task_list.yml` 声明。
- 注册表 `_CONFIGS: dict[str, type[ScriptConfig]]` 由 `@register` 装饰器显式填充，key 为 `_script_name`；路径声明不完整会在 import 时 assert 暴露。**注册表为模块私有，不对外 import**：外部只经模块级公开函数访问（`is_adapted` / `supports_weekly` / `get_config_path` / `get_game_exe_path` / `get_background_rel_path` / `iter_backup_paths` / `set_config` / `set_weekly_task_option`）。

## 统一任务声明

`config/task_list.yml` 按脚本组织任务列表，顶层 `type` 区分日常与周常。任务与选项共用 `display_name` / `physical_name`；省略物理名时使用展示名。任务有效物理名在脚本内唯一，列表顺序只控制展示。

`options` 是递归选项组：`key` 绑定该组选项的原生字段，`values` 与 `source` 二选一。`source: {path, category?}` 从子脚本根目录下的相对路径读取资源；省略 `category` 时沿用所在节点的有效物理名。只有一级选择时，值节点不再嵌套 `options`。纯展示分类省略外层 `options.key`，各分类的实际选项组绑定同一字段。

顶层 `key` 用于原生任务操作，如开关或任务列表；顶层 `allow_disable` 表示任务支持独立停用。子选项没有这两种任务属性，也不声明 `type`。

`task_config.py` 按文件版本缓存并校验声明，每次返回独立副本。service 展开资源为同结构的 `values` 并生成菜单；原生配置的读写仍由脚本适配器完成。声明允许递归，当前选择接口和 GUI 明确限制为两层。

## 三个独立流程

| 流程 | 触发时机 | 作用 |
|------|----------|------|
| 初始化 init | 已就绪但未接入任何触发点（调用时机待 review 定） | 确保脚本 config 与模板对齐，补全缺失结构 |
| 设置副本 set_daily_task | 外部调用 `set_config()` 时 | 按用户选择的副本/序列修改 config |
| 设置周常 set_weekly_tasks | 外部调用 `set_config()` 时 | 按周常起始日写周常开关，仅适配脚本支持 |

三者独立：初始化是防御性对齐，设置副本与周常是功能性响应。

## 落盘时机（何时调用 set_config）

子脚本 config 的落盘点按「能否在编辑期确定」分两类：

| 配置类型 | 落盘时机 | 说明 |
|----------|----------|------|
| 日常副本 / 序列（`option_name` / `sequence`） | **编辑期实时** | GUI 选副本（`TaskCardController.selectDailyTask`）经 service 调 `set_config` 实时写子脚本 config。无需等到运行全体。 |
| 周常副本（`set_weekly_task_option`） | **编辑期实时** | GUI 选周常副本（`selectWeeklyTaskOption`）直接写子脚本 config。 |
| 周常起始日（`weekly_start` → 周本开关） | **运行期** | 启用与否 = `today_weekday >= start_day`，只能在运行期按当天星期计算。故仅在 `generate_chain_config` 中经 `set_config(weekly_start=...)` 透传，由 `set_weekly_tasks` 写开关。 |

**关键结论**：除「按周几起决定开启/关闭」的周本开关必须在运行期落盘外，其余日常副本/序列、周常副本均在编辑期实时落盘子脚本 config。`generate_chain_config` 因此**不再重复写** dungeon/sequence——它只负责把 `weekly_start` 透传给 `set_config`。

> 未选择（`option_name` 为空或「未选择」）保持 no-op：不清空、不触碰子脚本 config。这里不做「清空支持」，避免误删用户在他处的手动配置。

> 历史包袱：早期子脚本 config 唯一的写盘点是「运行全体」时 `generate_chain_config` 内的 `set_config` 循环，导致编辑期改副本要等运行全体才生效。现改为编辑期实时落盘，运行全体路径不再负责 dungeon/sequence 落盘（仅周本开关）。

## 初始化流程 init

`ScriptConfig._init_config()`：仅对声明了 `_template_rel_path` 的脚本生效。先判模板是否存在（无模板直接返回），再 `self._load(allow_missing=True)` 读当前 config（脚本未安装/未配置返回 None 时直接返回，不触碰 config），然后 `_load_template()` 加载模板 → 若 `_is_aligned` 一致则跳过；否则遍历模板字段 `safe_update(..., assert_key_exists=False)` 合并补全并保存。`_is_aligned` 递归比较，dict 递归、list 按索引、其余直接比。

落点（触发时机）：`config_workflow()` 在每次启动时调用 `init_config_all()`，遍历所有已注册脚本对齐 config 与模板。新增/修改脚本路径时（`add_script` / `update_script`）也调用 `init_config`。无 `_template_rel_path` 直接返回、`self._load(allow_missing=True)` 缺失返回——守卫确保无模板或脚本未安装时为空操作。反读适配器（`get_daily_task` 等）一律不触发，保持纯只读。

| 脚本 | 当前调用 _init_config | 模板 | 说明 |
|------|---------------------|------|------|
| 鸣潮 | 是（no-op，无模板→直接返回） | — | 启动时自动触发，无模板时为空操作 |
| 原神 | 是 | `BGI一条龙.json` | 启动时自动触发，模板对齐补全缺失字段 |
| 终末地 | 是 | `okef一条龙.json` | 同上 |
| 绝区零 | 是 | `ZZZ一条龙.yml` | 同上 |
| 崩铁 | 是 | `M7A一条龙.yml` | 同上 |
| 异环 | 是（no-op，无模板→直接返回） | — | 同鸣潮 |
| 粥 | no-op（无模板） | — | 关卡别名由任务选项声明，原生作战队列仍由 MAA 适配器处理|

## 设置日常流程 set_daily_task

`set_daily_task(daily_name, option_name, sequence)` 先按有效物理名定位日常，再 `_load()` → `_update_daily_task(...)` → 有变化则 `_save()`。基类 `_update_daily_task` 按 `options.key` 直接更新字段并返回是否修改；子类先定位自己的配置段，再调用 `super()._update_daily_task`；`_read_daily_task(daily_name)` 用相同声明反读。没有别名的原生值保持可见，不额外维护映射。

一次选择涉及多个字段时先更新副本，全部校验成功才替换原对象；类型不符或缺少二级选择时不会留下部分修改。保存后 `_verify_saved()` 仍重读校验落盘一致性。

| 脚本 | 日常适配 |
|------|----------|
| 鸣潮 | 通用读写，一级原生分类与二级序列均由声明绑定 |
| 原神、终末地 | 一级为展示分类，只写二级原生副本名；资源通过声明路径反读 |
| 异环 | 两个独立日常，按物理名定位原生配置段和 Routine Item |
| 崩铁、绝区零 | 日常由上游自行管理，保留展示，选择写入为空操作 |
| 明日方舟 | 保留原生 TaskQueue 读写，关卡别名来自任务声明 |

异环的 `daily_anomaly` 与 `daily_anomaly_hunter` 分别对应「异象界域」「追猎目标」。修改一个日常只更新该段选择并启用对应 Routine Item；「不启用」只关闭对应任务，不清空选择或改变另一个日常。配置与启用状态分属 `DailyRoutineTaskConfigs.json`、`DailyRoutineTask.json`。

## 设置周常流程

周常副本读写由具体脚本实现，当前只有崩铁的 `instance_names` 适配；不经过日常读写入口。统一声明和菜单可保留相同选项结构，通用周常选项读写不在本轮扩展。

`set_weekly_task(weekly_name, start_day)` 更新单个周常；`set_weekly_tasks(start_day)` 批量更新全部。两者共用保存流程：校验 1~7 → 加载配置 → 在副本上逐项调用 `_write_weekly` → 全部成功且有变化时保存一次。周常声明为空时不支持周常；有独立周常路径则使用该文件。

各脚本保留原生规则：鸣潮增删追加任务，终末地更新反向开关，绝区零按应用 ID 更新 enabled，崩铁分别处理货币战争开关与历战余响起始日。MAA 根据 FightTask 状态更新吃药开关，并写 `MedicineExpireDays = 8 - start_day`。

`set_weekly_start_day` 仅由支持字面日期的脚本实现，编辑时不会切换运行期周常开关。用户的周几起和超时继续由 `weekly.yml` 保存。

## 安全字段更新 safe_update

`safe_update(config, key, value, display_name="", assert_key_exists=True) -> bool`：

- `assert_key_exists=True`：断言 `key in config`，并 `assert type(config[key]) is type(value)` 严格类型比较，避免 bool/int 混淆；值不同才写，返回是否修改。
- `False`：允许新增 key，缺失时 print 并写入，返回 True。
- 是所有字段写入统一入口，避免散落的 `.get()` 或直接赋值。

## 外部接口

```python
from src.config.set_config import set_config

set_config("ok-ww", daily_name="每日任务", option_name="凝素领域", sequence=17)          # 序列为数字
set_config("ok-ww", daily_name="每日任务", option_name="模拟领域", sequence="Shell Credit")       # 序列为字符串
set_config("ok-ww", weekly_start=3)                                # 周常起始日，仅适配脚本生效
set_config("ok-ww", daily_name="每日任务", option_name=None)                             # 跳过
set_config("ok-ww", daily_name="每日任务", option_name="未选择")                         # 跳过
```

`iter_backup_paths()` 返回 {script_name: 备份路径元组}——「该脚本的配置面在哪」的唯一声明处，供配置备份与恢复遍历。元素是**目录**（整目录递归打包）或**文件**（单文件收录），相对脚本根目录。仅用于收集文件，不解析或校验配置内容。

> 与读写路径（``_config_rel_path`` 等）刻意解耦：读写关心「哪个文件的哪个字段」，备份关心「配置面在哪」。声明了 ``_backup_paths`` 即表示该脚本要备份的配置全在这些路径里，备份层按条展开，不再回头拼读写路径。整目录形态用目录（ok-ww/ok-ef/ok-nte 的 ``working/configs``、BetterGI 的 ``User``、绝区零与粥的 ``config``），散装形态用文件（崩铁只要根目录 ``config.yaml``，其 ``config/`` 仅剩 workflows 故不声明）。

`set_config()` 接收 script_name；python/bat 脚本文件不在注册表内时优雅跳过。每次调用实例化对应子类；初始化独立进行；`weekly_start` 非 None 才写周常。

## 相关文件

| 文件 | 作用 |
|------|------|
| `set_config.py` | 本适配器，适配器接口 + 类层级；各脚本路径由子类声明，`@register` 显式注册 |
| `subscript.py` | config 读写基础设施，`get_script_name` / `load` / `save` / `load_template`，只接收 `rel_path`，不感知具体脚本 |
| `task_config.py` | `task_list.yml` 解析 |
| `src/link.py` | 游戏/脚本链接集中管理（官网、B 站、GitHub、banner 下载）；与 config 适配解耦。沿用基类 `GameLink` + 各脚本子类（`WutheringWavesLink`/`GenshinLink` 等）继承结构，`@register` 注册到 `_LINKS`，key 为 `_script_name`；本地背景图路径（`background`）仍声明在 set_config 子类，经 `_CONFIGS` 读取 |
| `config/task_list.yml` | 各脚本具名日常、周常的绑定字段、资源与选项 |
| `config/BGI一条龙.json` 等 | 各脚本 init 模板（粥无模板）|

## 如何新增一个游戏适配

1. `set_config.py` 新建 `ScriptConfig` 子类并加 `@register`，声明脚本名、配置路径、备份范围和可选模板、游戏路径。
2. 在 `config/task_list.yml` 添加具名任务及选项；普通日常复用基类，多日常按名称各自绑定。
3. 特殊原生配置在脚本类覆盖 `_update_daily_task` / `_read_daily_task` 或 `_write_weekly`，保持其他任务数据。
4. 补具名任务往返、失败隔离和 GUI 测试。

## 设计原则

- 两流程分离：初始化对齐模板与设置副本响应选择独立，不混。
- 克制：无明确收益不抽抽象。脚本原生规则留在现有适配器，任务通过声明和名称区分。
- 严格 assert：配置不一致立即报错，不静默容忍。字典访问先 assert key 再直接访问，不用 `.get()`。
- 类型一致：sequence 类型由 `task_list.yml` 的有效物理名决定，不做额外转换。

`get_game_path_keys(script_name, rel)` 复用打开游戏所用的路径声明，供恢复保留本机游戏路径；其他文件返回空元组。
