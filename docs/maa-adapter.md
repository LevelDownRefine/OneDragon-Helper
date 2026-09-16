# MAA 原生刷图适配

适配器只读写 `config/gui.new.json` 中的 `Configurations.Default.TaskQueue`。队列执行、关卡当天是否开放、理智消耗、剿灭周进度由 MAA 处理，OneDragon-Helper 不维护运行调度器或额外状态文件。

## 本项目的行为约定

- 三个独立入口：活动关卡、理智作战、剩余理智。每个入口保存一个固定关卡代码；名称和顺序来自 `daily_task_list.yml`，不保存活动序号。
- 普通关卡在 YAML 中维护；活动选项读取 MAA 本地 `StageActivityV2.json`，按客户端和活动时间筛选 `Value`，排除 `SSReopen-` 复刻导航指令。
- 初始化时补齐任务：唤醒后安排剿灭和活动，库存保持后安排理智作战和剩余理智。剿灭必刷，额外和重复 FightTask 清理，其他类型任务保持原有顺序及内容。
- 新入口从仓库的 `config/MAA任务.json` 创建。它是按原生字段编写的最小配置片段，不是用户配置快照，也不是 MAA 导出的完整默认配置；未列字段由 MAA 提供默认值。已有入口继续使用自己的设置，不复制其他入口。
- 接管单关卡、启用状态、备选关卡/周计划/次数/掉落限制开关。普通药、源石、连战及未接管字段保留原生值。未选关、多关卡计划均按未设置处理，保持停用。
- 所有战斗临期药常开。新任务继承现有战斗共同的 `MedicineExpireDays`，不一致时统一为 2 天；周常入口设置 `MedicineExpireDays = 8 - 起始星期`。
- 活动过期仅在初始化时停用，保留原代码；新活动须重新选择。菜单启动时缓存，保存选择时校验活动可用性，运行前不重建队列。

## MAA 字段及执行依据

核对版本：`7e5de9b3c137a448b715cdc622f27f667b5b7b7a`。这里只使用原生配置字段和资源格式，不移植上游 C# / C++ 的任务执行实现。

| 原生定义 | 适配所用的事实 |
| --- | --- |
| [BaseTask.cs](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaWpfGui/Configuration/Single/MaaTask/BaseTask.cs) | `$type` 标识任务种类，`Name` 为自定义名称，`IsEnable` 为开关 |
| [FightTask.cs](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaWpfGui/Configuration/Single/MaaTask/FightTask.cs) | `StagePlan`、限制和用药字段；连战默认 0，临期窗口默认 2 天 |
| [FightSettingsUserControlModel.cs](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaWpfGui/ViewModels/UserControl/TaskQueue/FightSettingsUserControlModel.cs) | 无开放关卡时跳过；次数及掉落限制由相应开关控制；剿灭选关使用 `UseCustomAnnihilation` 和 `AnnihilationStage` |
| [TaskQueueViewModel.cs](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaWpfGui/ViewModels/UI/TaskQueueViewModel.cs) | 原生队列按顺序处理启用任务 |
| [StageManager.cs](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaWpfGui/Services/StageManager.cs)、[StageActivityInfo.cs](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaWpfGui/Models/StageActivityInfo.cs) | 客户端资源、活动时区及开放区间；普通关卡的开放日由 MAA 管理 |
| [FightTask.cpp](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaCore/Task/Interface/FightTask.cpp) | `SSReopen-` 属于复刻导航指令 |

日常读写和开关由 `MaaDaily` 负责，`MaaActivityDaily` 增加活动选项及过期检查，`ArknightsConfig._init_config` 负责一次性编排。runner 子模块保持原有实现与版本。
