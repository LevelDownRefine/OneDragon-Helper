# 任务附带选项

`TaskOptions` 按 `config/task_switch_list.yml.options` 读写已接入任务的业务参数及完成后操作；与日常/周常分开，不承载基础设置、MAA、战斗策略或自由数字/文本输入。

## 声明

每组含 `display_name/config/tasks/fields`；config 相对脚本根目录，tasks 关联反读的原生任务名，`[]` 表示独立组。

字段含稳定 `id`、展示名、原生 `keys` 和 `type`。支持 `bool/choice/multi`，多选可设 `min_items`。候选来自 `values`（字符串或 display_name/physical_name）或本地 source：

| source 字段 | 读取方式 |
| --- | --- |
| path/prefix | 匹配目录内 JSON 文件，去除前缀 |
| path/key | 沿 JSON 键路径取列表或字典键 |
| path/field | 取 JSON 各记录的指定字段 |
| path/enum/argument | 用 Python AST 读取枚举构造参数，不导入或执行；prepend 可加「随机」 |

原生文件或字段缺失时隐藏选项，不补默认值、不创建文件。资源缺失或解码失败须记录诊断；当前值不在候选中仍保留回显。异环参数写 `DailyRoutineTaskConfigs.json` 任务节点，不能写独立任务 JSON。

## 展示与保存

子设置直接显示在任务下，保留原行高并缩进，不增加折叠或虚构总开关；独立单字段同名组只显示一行。没有附带选项的任务只显示原生开关。

`script_edit_view.task_options` 提供字段，前端通过 `ScriptEdit.task_options` 仅提交变化的 `id → value`。保存前重读并校验全部输入，拒绝未知字段、错误类型及非法候选，保留其他键。

共享文件时先存附带选项，再由任务开关重读修改。安装路径或脚本标识改变后先保存刷新，再编辑选项。原神 `CompletionAction` 同样只在用户修改时写回。
