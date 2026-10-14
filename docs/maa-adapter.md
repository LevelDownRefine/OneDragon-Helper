# MAA 刷图适配

只读写 `config/gui.new.json` 的 `Configurations.Default.TaskQueue`；队列执行、关卡开放、理智消耗与剿灭进度归 MAA，不另存调度状态。

## 行为

- 活动关卡、理智作战、剩余理智各存一个固定关卡代码，名字与顺序来自日常声明。普通关卡静态维护；活动从本地 StageActivityV2.json 按客户端和时间筛选，排除 SSReopen- 导航指令。
- 初始化在唤醒后安排必刷剿灭和活动，在库存保持后安排理智作战和剩余理智；清理额外/重复 FightTask，保留非战斗任务的内容与顺序。
- 新任务复制项目最小模板 `config/MAA任务.json`，未列字段由 MAA 默认；已有任务保留自己的设置，不借用其他入口。
- 接管单关卡、启用、备选关卡/周计划/次数/掉落限制开关；保留普通药、源石、连战及其他字段。未选关或多关计划视为未设置并停用。
- 初始化启用战斗临期药；新任务继承一致的 MedicineExpireDays，不一致用 2 天。周常写入 `8 - 起始星期`，禁用时关闭临期药。
- 活动过期仅在初始化时停用并保留代码，新活动须重新选择。菜单启动时缓存，运行前不重建队列，实际可用性由 MAA 判断。

`MaaDaily` 负责读写与开关，`MaaActivityDaily` 增加活动资源及过期检查，`ArknightsConfig._init_config` 编排队列。

## 上游依据

核对提交：`7e5de9b3c137a448b715cdc622f27f667b5b7b7a`。仅使用字段与资源格式，不移植任务执行实现。

| 原生定义 | 适配所用的事实 |
| --- | --- |
| [BaseTask.cs](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaWpfGui/Configuration/Single/MaaTask/BaseTask.cs) | `$type` 标识任务种类，`Name` 为自定义名称，`IsEnable` 为开关 |
| [FightTask.cs](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaWpfGui/Configuration/Single/MaaTask/FightTask.cs) | `StagePlan`、限制和用药字段；连战默认 0，临期窗口默认 2 天 |
| [FightSettingsUserControlModel.cs](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaWpfGui/ViewModels/UserControl/TaskQueue/FightSettingsUserControlModel.cs) | 无开放关卡时跳过；次数及掉落限制由相应开关控制；剿灭选关使用 `UseCustomAnnihilation` 和 `AnnihilationStage` |
| [TaskQueueViewModel.cs](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaWpfGui/ViewModels/UI/TaskQueueViewModel.cs) | 原生队列按顺序处理启用任务 |
| [StageManager.cs](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaWpfGui/Services/StageManager.cs)、[StageActivityInfo.cs](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaWpfGui/Models/StageActivityInfo.cs) | 客户端资源、活动时区及开放区间；普通关卡的开放日由 MAA 管理 |
| [FightTask.cpp](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/7e5de9b3c137a448b715cdc622f27f667b5b7b7a/src/MaaCore/Task/Interface/FightTask.cpp) | `SSReopen-` 属于复刻导航指令 |
