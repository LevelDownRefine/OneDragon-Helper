# set_config — 副本配置适配器

统一 `set_config()` 适配器接口，内部封装各游戏脚本异构的 config 读写。各脚本的 config 格式、路径、字段名不同，由各 `ScriptConfig` 子类适配，上层 service 不感知差异。

> 设计定位：`set_config` 是适配器，把异构 config 适配成统一调用；不是外观模式，外观整合职责归 `src/service/` 的 ChainService。

> script_name 为全链路内部唯一标识，由 `get_script_name(script)` 获取，与进程名 `get_process_name` 区分。exe 脚本的 script_name 即进程名 basename 去后缀，如 `ok-ww`；python/bat 脚本文件的 script_name 即 display_name。注册表、`dungeon_list.yml`、`gui_state.json`、`weekly_timeouts.yml` 的 key 全用 script_name，display_name 仅用于展示。config.yml 加载经 `check_script_name_uniqueness` 断言唯一。

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

- 基类 `ScriptConfig` 提供通用能力：`_load` / `_save` / `_verify_saved` / `_update_task` / `_update_sequence` / `_init_config` / `_is_aligned` / `set_dungeon` / `safe_update`。
- 子类声明 `_script_name`、`display_name` 与路径类属性：`_config_rel_path` 必填；声明了 `_game_path_keys` 则 `_game_config_rel_path` 必填；需模板初始化才设 `_template_rel_path`。`_task_key` / `_task_map` 按需覆盖。
- 注册表 `_CONFIGS: dict[str, type[ScriptConfig]]` 由 `@register` 装饰器显式填充，key 为 `_script_name`；路径声明不完整会在 import 时 assert 暴露。

## 两个独立流程

| 流程 | 触发时机 | 作用 |
|------|----------|------|
| 初始化 init | 子类 `__init__` 中调用 | 确保脚本 config 与模板对齐，补全/覆盖缺失结构 |
| 设置副本 set_dungeon | 外部调用 `set_config()` 时 | 按用户选择的副本/序列修改 config |

两者独立：初始化是防御性对齐，设置副本是功能性响应。

## 初始化流程 init

`ScriptConfig._init_config()` 默认：加载 config 与 template → 若 `_is_aligned` 则跳过；否则遍历模板字段 `safe_update(..., assert_key_exists=False)` 合并补全 → 保存。`_is_aligned` 默认递归比较，dict 递归、list 按索引、其余直接比，子类可覆盖。

各脚本 init 策略：

| 脚本 | 模板 | 对齐方式 | 状态 |
|------|------|----------|------|
| 鸣潮 | 无 | 不初始化；正确性由 `set_dungeon` 的 assert 隐式保证 | 完成 |
| 原神 | `BGI一条龙.json` | `_init_config` 只检查：assert 存在 `PartyName` 且 `_is_aligned` 一致，不修改 | 仅检查 |
| 终末地 | 无 | `_init_config` 目前 `pass` | 骨架 |
| 绝区零 | `ZZZ一条龙.yml` | `_init_config` 严格校验 `plan_list` 顺序，不一致则整体覆盖 | 完成 |
| 崩铁 | `M7A一条龙.yml` | 走基类默认对齐 | 基础 |
| 异环 | 无 | 不初始化；正确性由 `set_dungeon` 的 assert 隐式保证 | 完成 |
| 粥 | `MAA一条龙.json` | `_init_task_map` 从模板 `TaskQueue` 动态生成 `_task_map`，只取 `$type=="FightTask"`；基类 `_is_aligned` 比对 | 完成 |

## 设置副本流程 set_dungeon

基类模板流程：`_load()` → `_update_task()` → `_update_sequence()` → 有改动则 `_save()`，保存后 `_verify_saved()` 重读校验落盘一致性。

> 写盘校验：`_save()` 是唯一落盘点，写后 `_verify_saved()` 重读并与预期整段相等断言。save_config 为同步阻塞写，重读必为新内容，无需 sleep。校验失败属不该发生，用 assert。

| 钩子 | 作用 | 默认 |
|------|------|------|
| `_update_task(config, dungeon_name)` | 更新副本类型字段 | 设 `_task_key` 即启用，用 `_task_map` 映射，空 map 用 `dungeon_name` 原值 |
| `_update_sequence(config, dungeon_name, sequence)` | 更新序列字段 | `assert sequence is None` |

各脚本策略：

| 脚本 | 覆盖 set_dungeon | _task_key | 覆盖 _update_sequence | 说明 |
|------|-------------------|-------------|------------------------|------|
| 鸣潮 | 否 | `Which to Farm` | 是 | 模拟领域需映射值，凝素/无音区直接用 sequence |
| 原神 | 否 | `DomainName` | 否 | — |
| 终末地 | 否 | `体力本` | 否 | — |
| 崩铁 | 否 | `instance_type` | 否 | — |
| 异环 | 否，覆盖做互斥切换 | `任务类型` | 是 | 副本→序列字段名 `_seq_key_map`；`DailyRoutineTask.json` 切换 `daily_anomaly`↔`daily_anomaly_hunter` 互斥启用，复用基类 `_load`/`_save`，仅路径 `_routine_config_rel_path` 不同 |
| 绝区零 | 是，空实现仅 print | — | — | 无需适配副本选择 |
| 粥 | 是，完全自定义 | — | — | 禁用全部→启用剿灭+选定+土，直接操作 `TaskQueue` |

标准流程：不覆盖 set_dungeon，靠 `_task_key` + 可选 `_update_sequence` 适配；需完全自定义如粥或无需适配如绝区零才覆盖。

### 异环：追猎目标与异象界域互斥

异环日常玩法两类互斥：异象界域在 `DailyRoutineTaskConfigs.json` 的 `daily_anomaly` 段，追猎目标在 `daily_anomaly_hunter` 段。互斥开关写在 `DailyRoutineTask.json` 的 `Routine Items`，`id` 为 `daily_anomaly`/`daily_anomaly_hunter` 的 `enabled`。

NTEConfig 覆盖 `set_dungeon`：选空幕等异象界域副本 → 写 `daily_anomaly` 的 `任务类型`+序号，启用 `daily_anomaly`、停用 `daily_anomaly_hunter`；选追猎目标并选 boss → 在 `daily_anomaly_hunter` 写 `追猎目标`，启用 `daily_anomaly_hunter`、停用 `daily_anomaly`。

`_bind_section(dungeon_name)` 动态绑定段后，`set_dungeon` 直接 `super().set_dungeon()` 把第一份文件整套委托基类，自身只负责第二份互斥文件。相关路径/常量在 `NTEConfig`：`_routine_config_rel_path`、`_anomaly_dungeons`、`_exclusive_routine_items`、`_anomaly_seq_key_map`。

## 安全字段更新 safe_update

`safe_update(config, key, value, display_name="", assert_key_exists=True) -> bool`：

- `assert_key_exists=True`：断言 `key in config`，并 `assert type(config[key]) is type(value)` 严格类型比较，避免 bool/int 混淆；值不同才写，返回是否修改。
- `False`：允许新增 key，缺失时 print 并写入，返回 True。
- 是所有字段写入统一入口，避免散落的 `.get()` 或直接赋值。

## 外部接口

```python
from src.config.set_config import set_config

set_config("ok-ww", dungeon_name="无音区")       # 无序列
set_config("ok-ww", dungeon_name="凝素领域", sequence=17)   # 序列为数字
set_config("ok-ww", dungeon_name="模拟领域", sequence="贝币")  # 序列为字符串
set_config("ok-ww", dungeon_name=None)          # 跳过
set_config("ok-ww", dungeon_name="未选择")       # 跳过
```

`set_config()` 接收 script_name；python/bat 脚本文件不在注册表内，chain_gen 传 display_name 时优雅跳过。每次调用实例化对应子类并触发初始化。

## 相关文件

| 文件 | 作用 |
|------|------|
| `set_config.py` | 本适配器，适配器接口 + 类层级；各脚本路径由子类声明，`@register` 显式注册 |
| `subscript.py` | config 读写基础设施，`get_script_name` / `load` / `save` / `load_template`，只接收 `rel_path`，不感知具体脚本 |
| `dungeon_config.py` | `dungeon_list.yml` 解析 |
| `config/dungeon_list.yml` | 各脚本支持的副本及序列展示名，key 为 script_name |
| `config/MAA一条龙.json` 等 | 各脚本 init 模板 |

## 如何新增一个游戏适配

1. `set_config.py` 新建子类继承 `ScriptConfig` 并加 `@register`：设 `_script_name`、`display_name` 与路径类属性 `_config_rel_path` 必填、`_game_config_rel_path` 声明 `_game_path_keys` 时必填、`_template_rel_path` 需模板初始化才设。
2. 需初始化则实现 `_init_config` 并在 `__init__` 调用；设 `_task_key` / `_task_map`，需序列支持则覆盖 `_update_sequence`，标准流程不够则覆盖 `set_dungeon`。
3. `config/dungeon_list.yml` 加副本/序列选项，key 用 script_name。
4. 补测试 `tests/test_set_config_subclasses.py`。

## 设计原则

- 两流程分离：初始化对齐模板与设置副本响应选择独立，不混。
- 克制：无明确收益不抽抽象。异环多副本共用才抽 `_seq_key_map`，鸣潮单副本不抽。
- 严格 assert：配置不一致立即报错，不静默容忍。字典访问先 assert key 再直接访问，不用 `.get()`。
- 类型一致：sequence 类型由 `dungeon_list.yml` 的 value 决定，不做额外转换。
