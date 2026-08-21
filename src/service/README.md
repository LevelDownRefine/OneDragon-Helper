# src/service — 外观层 facade

整合其余部分的外观：把 set_config、runner、gui_state.json、链生成与校验内聚为统一薄接口，对 GUI 与 CLI 暴露同一套调用面。从 src/gui/ 分离而出，无 Qt 依赖，故 GUI 与 CLI 共用同一实现，也便于无头测试。

## 设计定位

| 角色 | 说明 |
|------|------|
| 外观，非适配器 | set_config 才是适配器；本层负责整合，是项目唯一外观 |
| 双入口薄适配 | GUI 与 CLI 都只做薄委托，真实实现在本层 |
| 写盘唯一路径 | config.yml 写入权统一归 ChainService |
| 无 Qt 依赖 | 纯业务逻辑，不承载 UI 渲染 |

## 文件

| 模块 | 职责 |
|------|------|
| chain_service.py | 核心 facade：config.yml 完整读写、UI 状态持久化、脚本链生成、合法性校验、runner 命令构造 |
| script_service.py | 单脚本视角：config.yml 单条目只读、weekly_timeouts.yml 读写与改名迁移 |
| chain_gen.py | 脚本链配置生成：由 enabled_names + gui_state 生成链配置并校验 |

## 依赖方向

```
launcher.py CLI  ┐
                 ├─▶ ChainService facade ─▶ set_config / runner / subscript / utils_runner
MainWindow  GUI  ┘
```

调用方不感知 weekly_timeouts 同步、链合法性校验、runner 命令构造等细节，全部内聚在 service/。
