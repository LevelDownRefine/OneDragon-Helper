# src/service — server / 外观层（facade）

整合其余各部分的**外观（facade）**：把 `set_config`（配置适配）、`runner`（脚本链执行）、`gui_state.json`（UI 状态）、链生成与校验等内聚为统一薄接口，对 GUI 与 CLI 暴露同一套调用面。从 `src/gui/` 分离而出——原先散落在 `MainWindow` / `src.gui.chain` 里的链编排、单脚本、状态逻辑逐步迁入，**无 Qt 依赖**，因此 GUI 与 CLI（`launcher.py`）可共用同一实现，也便于无头测试。

## 设计定位

| 角色 | 说明 |
|------|------|
| **外观（facade）**，非适配器 | `set_config` 才是适配器（适配各脚本异构 config）；本层负责「整合」，是项目里唯一的外观。 |
| 双入口薄适配 | GUI（`MainWindow`/`QmlBridge`）与 CLI（`launcher.py`）都只做薄委托，真实实现在本层。 |
| 写盘唯一路径 | config.yml 写入权统一归 `ChainService`；GUI 弹窗不直接写盘，经本层落地。 |
| 无 Qt 依赖 | 不承载 UI 渲染 / 弹窗，纯业务逻辑。 |

## 文件

| 模块 | 职责 |
|------|------|
| `chain_service.py` | 核心服务（GUI / CLI 唯一 facade）：config.yml 完整读写（含单脚本字段更新）、UI 状态持久化（gui_state.json）、脚本链生成、合法性校验、runner 命令构造。 |
| `script_service.py` | 单脚本视角：config.yml 单条目只读查询、weekly_timeouts.yml 读写与改名迁移。 |
| `chain_gen.py` | 脚本链配置生成（纯逻辑）：由 `enabled_names` + gui_state 选项生成链配置并校验，自 `src.gui.chain` 迁出。 |

## 依赖方向

```
launcher.py (CLI)  ┐
                   ├─▶ ChainService (facade) ─▶ set_config / runner / subscript / utils_runner
MainWindow  (GUI)  ┘
```

调用方不感知 weekly_timeouts 同步、链合法性校验、runner 命令构造等细节；这些全部内聚在 `service/`。
