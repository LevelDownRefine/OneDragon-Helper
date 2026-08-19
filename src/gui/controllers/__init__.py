"""QmlBridge 的职责 mixin 包：各控制器按职责拆分，由 main_window.QmlBridge 组合。

共享基类 BridgeBase（service / 共享状态 / 信号）与六个职责 mixin：
background / game_list / task_card / launch / links / window。
"""
