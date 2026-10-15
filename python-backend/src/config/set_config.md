# 配置适配器

`set_config.py` 将外部脚本的配置格式、路径和字段适配为统一接口；业务编排归 [AppService](../service/README.md)。

`script_name` 是全链路标识：EXE 使用文件名去后缀，Python/BAT 使用展示名。注册表和各声明以它为键，加载主配置时检查唯一性。

## 对象与入口

`ScriptConfig` 通过 `build_dailies/build_weeklies` 装配并持有任务对象，每条日常或周常一个实例；`Daily/Weekly` 自持配置 I/O，不在调用链上传递配置字典。

脚本实例通过私有 `_CONFIGS` 缓存，外部只用模块级公开接口。原生配置仍逐次读盘；修改脚本路径或标识后清除适配器缓存。基类只装配任务，MAA 构造时另行初始化队列。

| 接口 | 职责 |
| --- | --- |
| `get_daily_map/get_weekly_map` | 直接装配任务并调用 `menu()`，不触发脚本级初始化 |
| `set_config/get_daily_readback` | 选择日常、反读当前配置 |
| `set_daily_enabled` | 只改日常开关，保留副本选择 |
| `set_weekly_task/get_weekly_task` | 周常副本读写 |
| `set_weekly_start_day` | 编辑期同步字面起始日等字段 |
| `prepare_weekly_start_days` | 运行期按周几起准备开关 |
| `weekly_names/supports_weekly` | 只读声明，不初始化原生配置 |

## 游戏启动入口

终末地沿用原生配置中的游戏本体路径，手填 `game_path` 优先；`game_arguments`
只传给游戏本体，游戏进程仍为 `Endfield.exe`。`link` 将已解析的路径和参数交给
独立 CLI，CLI 直接调用 `utils_launcher.launch_game`，避免等待启动器时阻塞界面。
启动模块独立负责复用或定位官方启动器、校验签名、等待 `Games.exe`，再创建游戏。
终末地启动器声明集中在 `EndfieldConfig.launcher`，其中 `arguments` 固定为
`("--game=Endfield", "--reason=4")`，无需填入游戏参数。现有 `register()`
按游戏 EXE 文件名将声明装配到 `utils_launcher.LAUNCHERS`；`utils_launcher`
只负责通用的启动器查找、签名校验与游戏进程创建。

启动器查询共用 Windows 卸载记录的 HKCU/HKLM、32/64 位视图及 `InstallLocation`。
终末地卸载项为 `33a0a6296a20400d503c59ac0fd6341e`；异环仍由 `NTEConfig`
使用 `YH` 查找启动器，失败时保留从游戏目录向上查找的回退。

## 任务声明

日常在 `config/daily_task_list.yml`，周常在 `config/weekly_task_list.yml`，按脚本分组。共同规则：

| 字段 | 含义 |
| --- | --- |
| `display_name` | 展示名及声明层匹配键 |
| `physical_name` | 原生值，省略时使用展示名；保留字符串、整数、布尔类型 |
| `class`、`config` | 必填机制类及相对脚本根目录的配置文件 |
| `options.key` | 原生落点字段 |
| `options.values/source` | 静态选项或本机资源，二选一 |
| `enable_key/enable_task` | 按机制声明开关字段或任务名，无声明则无独立禁用入口 |
| `routine`、`template` | 日常的独立开关文件或模板，按机制使用 |

机制类分别在 `DAILY_CLASSES/WEEKLY_CLASSES` 注册。`task/task_declarations.py` 校验声明；展示名称只来自声明，不在 Python 中复制。

`source.path` 指定资源文件，`source.key` 是逐层键列表，省略或 `[]` 读根节点；末层取字符串列表或字典键，保留资源顺序。BGI 的 `source.category` 用于筛选资源类别，不能与 `source.key` 并用。

菜单保留 `display_name/physical_name/options.values`，剥离配置路径等机制字段；日常最多两级、周常最多一级，超出即报错。资源缺失时对应列表为空，返回菜单是独立副本，不持当前选择。

## 日常读写

选择时按日常展示名查对象，写副本后启用该日常已有的开关；未选择、空任务或「未选择」为 no-op，不清空原生配置。禁用仅改开关，不改变副本。

反读为 `{name, task, sequence, enabled}`，顺序同声明；副本反读不受启用状态影响。配置未安装或无开关时返回 `None`，不能显示成已停用。配置损坏、非法类型和未知值按机制报错；可恢复的任务定位失败须记录诊断。

| 机制 | 用途 |
| --- | --- |
| `Daily` | 标准两级落点，如鸣潮 |
| `SingleLayerDaily` | 单字段选择，日常名作为唯一一级项 |
| `BgiDaily/BgiLeyLineDaily/BgiStygianDaily` | 原神资源、任务开关及特殊字段；地脉花写一周七天，反读要求一致 |
| `MultiSelectEnabledDaily` | 终末地列表成员开关，只增删目标任务；缺失列表告警并返回无状态 |
| `TemplateDaily` | 绝区零启用时对齐模板；不启用不写、不撤回已有模板 |
| `Anomaly/AnomalyHunter` | 异环分段数据与独立 Routine 开关，两日常互不影响 |
| `MaaDaily/MaaActivityDaily` | MAA TaskQueue/StagePlan 与活动资源 |

BGI 按任务名反查启用表 ID；旧配置没有 `TaskDefinitions` 时使用任务名键。无法唯一定位或启用项异常时告警并返回未配置，不影响其他日常。

原神完成后操作由 [任务附带选项](task/task_options.md) 反读，修改时才写入。MAA 的初始化、字段所有权和活动规则见 [MAA 适配](../../../docs/maa-adapter.md)。

## 周常与落盘时机

`weekly.yml.weekly_start` 保存 `{脚本: {周常展示名: 起始日}}`：`0` 禁用，`1…7` 为周一至周日，缺席表示未设置、不改原生开关。旧脚本级整数按现有周常展开并写回，无法展开的条目告警后丢弃。

任务卡是「周几起」唯一界面入口；按条保存不触碰其他周常。旧 CLI `--weekly-start` 仍将一个值应用于该脚本全部周常。

| 时机 | 写入 |
| --- | --- |
| 编辑日常或周常副本 | 立即写原生配置 |
| 编辑起始日 | 先存助手意图，再写历战余响的字面日/开关或 MAA 用药窗口 |
| 运行前 | 对需要门控的周常，按当天星期更新开关 |

鸣潮幻梦游园、绝区零迷失之地、崩铁货币战争和模拟宇宙按「今天已到起始日」门控。历战余响写 `echo_of_war_start_day_of_week`，由上游判断；禁用时只关总开关。MAA 写 `MedicineExpireDays = 8 - 起始日`，禁用时关临期药并保留窗口。

`generate_chain_config` 只生成链，不写子脚本配置。周常对象由脚本持有，`weekly.py` 不另设缓存。

## 字段与文件安全

字段更新统一用 `utils_dict.safe_update`：默认要求键存在，检查类型并区分 bool/int，有变化才写；允许新增时缺失须告警。文件 I/O 经 `utils_sub_config`，保存后立即反读并断言与预期相等，不需要等待。

纯任务开关由 `native_task_switch.py` 按 `task_switch_list.yml` 枚举，不混入日常/周常。附带业务选项由 `TaskOptions` 自持读写；备份范围、游戏路径和链接见 [脚本资源](script_resources.md)。

## 扩展

1. 新脚本注册 `ScriptConfig` 子类，添加同名资源声明。
2. 在日常/周常 YAML 选择已有机制并声明落点；同机制加任务无需改 GUI。
3. 只有声明无法表达的读写才增加机制类；特殊初始化由脚本子类自持。
4. 补落盘、反读及字段保留测试；行为改变时审查 golden 差异，按 [测试指南](../../../docs/TESTING.md) 验证。

鸣潮、异环的选项由 Action 同步，其他动态资源在运行时读取；维护规则见 [工具指南](../../../tools/README.md)。
