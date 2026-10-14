# AGENTS.md

OneDragon-Helper 是多游戏脚本调度器：GUI 选择任务 → 写原生配置 → runner 执行脚本链 → 分析日志并汇总。

## 环境与仓库

- Python 3.11+，根目录 uv workspace 统一管理 `.venv/` 和 `uv.lock`；改代码前运行 `uv sync` 并激活环境（Windows Bash：`source .venv/Scripts/activate`；CMD：`call env.bat`）。
- `rust-gui/` 为 egui/eframe 前端，`python-gui/` 为 PySide6/QML 前端，`python-backend/` 为无 Qt 业务后端。共享 config、assets、tools、deploy 留在根目录，源码和测试归各子项目。
- `runner/`（OneDragonRunner）和 `updater/`（LevelDownRefine/updater）是独立 Git 子模块：改动在子仓提交并先推送，主仓只更新指针。`leveldown-updater` 从本地子模块严格可编辑安装。
- Python 使用 ruff，行长 88、双引号；完整规则见 [编码约定](docs/CONVENTIONS.md)。

## 架构边界

| 层 | 职责与详细说明 |
| --- | --- |
| [配置适配器](python-backend/src/config/set_config.md) | 适配原生配置路径、格式和字段，不承担 service 外观职责 |
| [runner](runner/README.md) | 按链逐条执行，block 控制阻塞 |
| [Rust GUI](rust-gui/README.md) / [Qt GUI](python-gui/src/gui/README.md) | 纯界面、控制器和弹窗；不写配置、不承载业务 |
| [service](python-backend/src/service/README.md) | AppService 统一整合读写、校验、链及运行命令，无 Qt 依赖 |

更新内核归 updater 子库；助手适配、UpdateSession 与独立更新器入口集中在 `python-backend/src/update.py`，由 AppService 薄委托。

## 声明与所有权

- 日常/周常分别在 `config/daily_task_list.yml`、`weekly_task_list.yml`，统一 display_name/physical_name 和递归 options；class 注册表选择机制，config/routine 指定落点，名字只来自声明。
- `ScriptConfig` 通过 build_dailies/build_weeklies 装配并持有对象，一条任务一个实例。Daily/Weekly 自持原生 I/O，weekly 不设独立缓存；菜单直接装配任务，不触发脚本级初始化。
- 周几起是条目级，0 禁用；界面入口只在任务卡。日常有 enable_key/enable_task 声明才提供独立开关，异环两个日常各段、各开关。
- 原生任务开关在 `config/task_switch_list.yml`，由 native_task_switch 枚举并按原生任务名定位，展示于脚本配置「任务」区，不混入日常/周常。
- [附带业务选项](python-backend/src/config/task/task_options.md) 同文件 options 声明，TaskOptions 自持读写。支持开关、单选、多选及原神完成后操作，不含基础设置或 MAA；前端经 ScriptEdit.task_options 只提交改动。
- [脚本资源](python-backend/src/config/script_resources.md) 统一在 script_resources.yml，含备份、游戏路径落点、背景和链接；不放用户安装路径，加载器只读校验，机制归 Python。
- [日志位置和规则](python-backend/src/log/README.md) 在 log_analysis.yml；log_path 为实时日志，log_analysis_path 可指定分析文件，service 生成链时注入 runner。schedule_run 编排分析、重跑和汇总。
- 缺失主配置由 config_workflow 从模板生成。原神/终末地等动态选项读本地资源，静态名单手工维护；鸣潮/异环的 Action 同步规则见 [工具指南](tools/README.md)。

## 必须遵守

- 不可能发生的事用 assert；可恢复错误显式处理。
- 字典先 assert 键存在再索引，不用无默认值的 .get()；例外边界见编码约定。
- 不静默吞异常，捕获尽量指定类型；日志用 logging，禁止裸 print。
- 功能改动必须补测试；改完运行两套 Python 全量测试、ruff check 和 ruff format --check，命令见 [测试指南](docs/TESTING.md)。两套件分开跑，格式失败修复后重查。
- 不动 .bak 或备份，除非先获用户同意。
- Commit 使用 Conventional Commits 前缀及 ≤50 字符主题；注释和备注只写要点。
