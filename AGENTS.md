# AGENTS.md

OneDragon-Helper 项目指南。细节与澄清见各子文档。

## 项目是什么

多游戏自动化脚本调度器：GUI 选脚本/副本/超时 → 写各脚本自己的 config → 运行器逐条 subprocess 调外部 exe → 解析日志汇总成功/失败。

## 技术栈

- Python 3.11+；GUI 用 PySide6，原生控件加手写样式；Lint/Format 用 ruff，line-length 88，双引号。
- 依赖用 `uv sync`，即 `pyproject.toml` + `uv.lock`；改代码前先 `source .venv/Scripts/activate`，或 `call env.bat`。
- **`src/runner/` 是 git submodule → OneDragonRunner，独立仓库维护**：涉及 runner 的改动要进那个仓库单独提交/推送，主仓只更新 submodule 指针。

## 架构：四部分，职责单向、互不越界

1. **set_config：副本配置适配器** — 把各游戏脚本异构的 config 格式/路径/字段名适配成统一接口 `set_config()`。它是 adapter 而非 facade，facade 职责归 service。详见 `src/config/set_config.md`。
2. **runner：脚本链运行器，submodule** — 逐条执行脚本链，`block` 字段控制阻塞/非阻塞。详见 `src/runner/README.md`。
3. **gui** — 只放纯图形界面，即 QML、控制器与弹窗；**不写盘、不承载业务逻辑**，写盘统一经 service。详见 `src/gui/README.md`。
4. **service，外观/facade** — 整合 config 读写·UI 状态·链生成·校验·runner 命令，对 GUI/CLI 暴露统一薄接口，无 Qt 依赖，从 gui 分出。详见 `src/service/README.md`。

> 副本列表 `config/dungeon_list.yml` 各游戏维护方式不同：终末地/鸣潮/异环走 GitHub Action，原神走手动 skill，其余固定；日志解析 `scripts/collect_log.py`、失败重跑 `scripts/rerun.py`；初始化由 `config_workflow()` 在 `config.yml` 缺失时模板生成。

## 铁律：违反即打回

- 不可能发生的事用 `assert`；可恢复才 `return False`/跳过。
- 字典先 `assert key in d` 再 `d[key]`，不用 `.get()`。
- 不静默吞异常：`except` 不许 `pass`/裸吞，必须显式处理；克制用 try，except 尽量显式类型。
- 日志用 `logging`，`logger = logging.getLogger(__name__)`，禁止裸 `print`，`collect_log.py` 例外。
- 改完必须补测试 + 跑全套：`PYTHONPATH=src python -m unittest discover -s tests -p "test*.py"` 且 `ruff check src tests`。
- 不动 `.bak`/备份文件，除非先问用户。
- Commit 用 Conventional Commits 前缀 + ≤50 字主题；备注/注释只写要点。

完整编码约定，含每条的理由与边界，见 **`CONVENTIONS.md`**；测试与工作流见 **`TESTING.md`**；副本同步见 **`tools/README.md`**。
