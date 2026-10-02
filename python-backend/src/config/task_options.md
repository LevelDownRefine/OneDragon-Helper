# 任务附带选项

`task_options.py` 根据根目录 `config/task_options.yml` 读写已接入任务的业务参数。
不承载基础设置、MAA、战斗策略、自由数字或文本输入；与日常/周常、原生任务开关分开。

每个脚本声明若干组：`display_name` 为任务名，`config` 为相对脚本安装目录的原生文件，
`fields` 每项包含稳定的 `id`、展示名、原生 `keys` 键路径和 `type`。
支持 `bool`、`choice`、`multi`；多选可声明 `min_items`。当前值只反读原生配置。
文件或字段不存在时不显示该选项，不补默认值、不创建配置文件。

选择项通过 `values`（字符串列表或 `display_name/physical_name` 映射）或本地 `source` 提供：

- `path/prefix`：枚举该目录里匹配前缀的 JSON 文件名，移除前缀；用于 BGI 领奖地区。
- `path/key`：沿 JSON 键路径读取列表或字典键；用于终末地送货地区。
- `path/field`：读取 JSON 字典中各记录的指定字段；用于终末地送礼对象。
- `path/enum/argument`：读取 Python AST 中指定枚举类构造调用的字符串参数；
  用于绝区零录像店宣传员，不执行或导入外部 Python。`prepend` 可添加「随机」。

异环一条龙参数落在 `DailyRoutineTaskConfigs.json` 的任务节点内，不能写独立任务 JSON。
本地资源缺失或无法解码时隐藏受影响选择并记录诊断；当前值不在候选列表时保留回显，
避免编辑其他字段时清除上游新增值。

`AppService.script_edit_view` 返回 `task_options` 字段列表；前端只提交相对打开时变化的
`id → value`，经 `ScriptEdit.task_options` 与 `script.edit_save` 保存。读写与校验归后端，
GUI 仅负责控件。保存前重新读取原生文件、校验全部输入，拒绝未知字段、错误类型和非法
候选值，保留其他键。选项与任务开关共用文件时先保存选项，开关随后重读并修改同一文件。
修改安装路径或脚本标识时，先保存并刷新，再编辑附带选项。
