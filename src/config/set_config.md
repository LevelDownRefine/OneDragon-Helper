# set_config — 副本配置适配器

对外提供统一的 `set_config()` 外观接口，内部封装各游戏脚本千差万别的 config 读写逻辑。每个脚本的 config 格式、路径、字段名都不同，由各 `ScriptConfig` 子类单独适配，上层（GUI）无需关心差异。

## 架构

**外观模式 + 类层级**（非模板方法）：

```
上层调用 ─▶ set_config(name, dungeon_name, sequence)  # 外观接口
                │ 判空跳过 → 查 _CONFIGS 注册表 → 构造子类 → set_dungeon()
                ▼
          ScriptConfig（基类）
                │ 继承
   ┌──────┬──────────┬──────────┬──────┬──────┐
   ▼      ▼          ▼          ▼      ▼      ▼
 鸣潮   原神/终末地  绝区零/崩铁  异环    粥
```

- 基类 `ScriptConfig` 提供通用能力：`_load` / `_save` / `_update_task` / `_update_sequence` / `_init_config` / `_is_aligned` / `set_dungeon` / `safe_update`。
- 子类在 `__init__` 设 `display_name` / `_task_key` / `_task_map`，按需覆盖方法。
- 注册表 `_CONFIGS: dict[str, type[ScriptConfig]]` 把 `display_name` → 子类。

## 两个独立流程

| 流程 | 触发时机 | 作用 |
|------|----------|------|
| **初始化（init）** | 子类 `__init__` 中调用 | 确保脚本 config 与模板对齐，补全/覆盖缺失结构 |
| **设置副本（set_dungeon）** | 外部调用 `set_config()` 时 | 按用户选择的副本/序列修改 config |

两者独立：初始化是防御性对齐，设置副本是功能性响应。

## 初始化流程（init）

`ScriptConfig._init_config()` 默认逻辑：加载 `config` 与 `template` → 若 `_is_aligned` 则跳过；否则遍历模板字段 `safe_update(..., assert_key_exists=False)` 合并补全 → 保存。`_is_aligned` 默认递归比较（dict 递归、list 按索引逐项、其余直接比），子类可覆盖以实现特殊比较。

各脚本 init 策略（当前代码）：

| 脚本 | 模板 | 对齐方式 | 状态 |
|------|------|----------|------|
| 鸣潮 | 无 | 不初始化；检查由 `set_dungeon` 的 assert 隐式承担 | 完成 |
| 原神 | `BGI一条龙.json` | `_init_config` 只检查：assert 存在 `PartyName` 且 `_is_aligned` 一致；**不修改**（TODO 未适配） | 仅检查 |
| 终末地 | 无 | `_init_config` 目前 `pass`（占位，TODO） | 骨架 |
| 绝区零 | `ZZZ一条龙.yml` | `_init_config` 调 `_is_aligned` 严格校验 `plan_list` 顺序（不一致则整体覆盖） | 完成 |
| 崩铁 | `M7A一条龙.yml` | `_init_config` 走基类默认对齐 | 基础 |
| 异环 | 无 | 不初始化；检查由 `set_dungeon` 的 assert 隐式承担 | 完成 |
| 粥 | `MAA一条龙.json` | `_init_task_map` 从模板 `TaskQueue` 动态生成 `_task_map`（只取 `$type=="FightTask"`）；基类 `_is_aligned` 比对 | 完成 |

> 无模板/无 `_init_config` 的脚本（鸣潮、异环）：结构正确性由 `set_dungeon` 中的 `assert` + `config[key]` 直接访问（缺 key 抛 KeyError）隐式保证。

## 设置副本流程（set_dungeon）

基类模板流程：`_load()` → `_update_task()` → `_update_sequence()` → 有改动则 `_save()`。

| 钩子 | 作用 | 默认 |
|------|------|------|
| `_update_task(config, dungeon_name)` | 更新副本类型字段 | 设 `_task_key` 即启用，用 `_task_map` 映射（空 map 则用 `dungeon_name` 原值） |
| `_update_sequence(config, dungeon_name, sequence)` | 更新序列字段 | `assert sequence is None`（即默认不支持序列） |

各脚本策略：

| 脚本 | 覆盖 `set_dungeon` | `_task_key` | 覆盖 `_update_sequence` | 说明 |
|------|-------------------|-------------|------------------------|------|
| 鸣潮 | 否 | `Which to Farm` | 是 | 模拟领域需映射值，凝素/无音区直接用 `sequence` |
| 原神 | 否 | `DomainName` | 否 | — |
| 终末地 | 否 | `体力本` | 否 | — |
| 崩铁 | 否 | `instance_type` | 否 | — |
| 异环 | 否 | `任务类型` | 是 | 用 `_seq_key_map`（副本→序列字段名）驱动 |
| 绝区零 | 是（空实现，仅 print「zzz无需适配」） | — | — | 无需适配副本选择 |
| 粥 | 是（完全自定义） | — | — | 禁用全部→启用剿灭+选定+土，直接操作 `TaskQueue` |

> 标准流程：不覆盖 `set_dungeon`，靠 `_task_key` + 可选 `_update_sequence` 适配。需完全自定义（粥）或无需适配（绝区零）才覆盖。

## 安全字段更新 `safe_update`

`set_config.safe_update(config, key, value, display_name="", assert_key_exists=True) -> bool`：

- `assert_key_exists=True`：断言 `key in config`，并 `assert type(config[key]) is type(value)` 严格类型比较（避免 bool/int 混淆），值不同才写，返回是否修改。
- `False`：允许新增 key，缺失时 `print` 并写入，返回 True。
- 这是所有字段写入的统一入口，避免散落的 `.get()` / 直接赋值。

## 外部接口

```python
from src.config.set_config import set_config

set_config("鸣潮", dungeon_name="无音区")                       # 无序列
set_config("鸣潮", dungeon_name="凝素领域", sequence=17)        # 序列为数字
set_config("鸣潮", dungeon_name="模拟领域", sequence="贝币")     # 序列为字符串
set_config("鸣潮", dungeon_name=None)        # 跳过
set_config("鸣潮", dungeon_name="未选择")     # 跳过
```

每次调用都会实例化对应子类（`__init__` 触发初始化），再调 `set_dungeon`。

## 相关文件

| 文件 | 作用 |
|------|------|
| `set_config.py` | 本适配器（外观 + 类层级） |
| `subscript.py` | config 读写基础设施（`_CONFIG_REL_PATHS` / `_TEMPLATE_PATHS` / `load` / `save` / `load_template`） |
| `dungeon_config.py` | `dungeon_list.yml` 解析（一级/二级选项） |
| `config/dungeon_list.yml` | 各脚本支持的副本及序列展示名 |
| `config/MAA一条龙.json` · `BGI一条龙.json` · `ZZZ一条龙.yml` · `M7A一条龙.yml` | 各脚本 init 模板 |

## 如何新增一个游戏适配

1. `subscript.py` 的 `_CONFIG_REL_PATHS` 加 config 相对路径；需要模板则加 `_TEMPLATE_PATHS` 并在 `config/` 建模板。
2. `set_config.py` 新建子类继承 `ScriptConfig`：设 `display_name`；初始化需要则实现 `_init_config` 并在 `__init__` 调用；设 `_task_key` / `_task_map`，需序列支持则覆盖 `_update_sequence`，标准流程不够则覆盖 `set_dungeon`。
3. 在 `_CONFIGS` 注册表登记。
4. `config/dungeon_list.yml` 加副本/序列选项。
5. 补测试（`tests/test_set_config_subclasses.py`）。

## 设计原则

- **两流程分离**：初始化（对齐模板）与设置副本（响应选择）独立，不混。
- **克制**：无明确收益不抽抽象。异环多副本共用同逻辑才抽 `_seq_key_map`；鸣潮单副本不抽。
- **严格 assert**：配置不一致立即报错，不静默容忍。字典访问先 `assert key in dict` 再直接访问，**不用 `.get()`**。
- **类型一致**：sequence 类型由 `dungeon_list.yml` 的 `value` 决定，不做额外转换。
