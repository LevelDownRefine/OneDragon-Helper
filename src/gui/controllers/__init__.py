"""QmlBridge 的职责控制器包：各控制器按职责拆分，由 main_window.QmlBridge 组合。

每个控制器是独立的 QObject，自管状态 + 自己的信号 / 槽：
- background：背景模式 / 壁纸 / 视频错误回退
- game_list：脚本列表 / 当前选中 / 启用态 / 控制模式 / 重排 / 增删 / 配置弹窗
- task_card：日常副本 / 周常周几（数据 + 选择持久化）
- launch：启动全部 / 启动当前脚本 / 运行前校验 / 生成并运行链
- links：主页 / B站 / GitHub / 脚本目录 / 设置 / 启动游戏
- window：系统原生拖动 / 最小化 / 关闭

跨控制器依赖经构造注入（如 background / task_card / launch 持有 game_list 引用），
跨控制器流程（切选中 -> 刷背景 / 任务卡）由 main_window.QmlBridge 经信号转发 + 编排。
"""
