# 任务配置

本包集中任务声明与配置机制，统一入口仍由上层 `set_config.py` 和 service 提供。

- `task_declarations.py`：读取和校验日常、周常声明，提供物理名及选项取值的共用规则。
- `daily.py`、`weekly.py`：解释各自落点和菜单，自持原生配置读写。
- `task_source.py`、`maa_activity.py`：读取候选资源；MAA 活动资源保留独立格式处理。
- `native_task_switch.py`：外部脚本自带任务的开关，与本工具的日常、周常条目区分。
- `task_options.py`：已接入任务的附带业务选项，格式见 [业务选项](task_options.md)。

根目录 `config/` 中的 YAML 声明位置不变。
