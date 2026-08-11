# src/gui — GUI 包

PySide6 GUI：脚本列表、增删/重排/配置、生成脚本链配置并运行。

## 文件与依赖

| 模块 | 项目内依赖 |
|------|-----------|
| `main_window` | widgets / dialogs / runner / theme / utils / config.dungeon_config / service.chain_service / service.script_service / src.utils |
| `widgets` | dialogs / icons / theme / runner / utils / config.dungeon_config / config.subscript |
| `dialogs` | theme / utils / src.utils / service.script_service |
| `icons` | src.utils |
| `utils` | theme / src.utils |
| `theme` | （无项目内依赖，纯样式层） |
| `runner` | src.utils |

依赖单向：`main_window` 是唯一入口，其余模块不反向引用主窗口。`theme` 被各 GUI 模块引用，但自身不依赖任何业务模块。

## 主题与样式（`src/gui/theme.py`）

所有 GUI 模块的视觉样式（颜色、字号、QSS、按钮构造）统一从 `theme.py` 取，**业务代码禁止写裸色值 / 裸 QSS 字符串**。

- **设计 token**：甘雨五色 `DARK_BLUE / BLUE / SKY_BLUE / BEIGE / CRIMSON`；语义色基本直接引用五色，`BORDER_WIDTH = "1px"` 统一边框宽度。`BG_MUTED` 因原米色与极淡蓝主背景不协，改用派生冷灰蓝 `#E8EEF5`。
- **字体 / 字号**：`FONT_FAMILY`（微软雅黑优先）+ `make_font()` 统一构造像素字号 `QFont`；`FONT_SIZE_BODY / FONT_SIZE_BTN / FONT_SIZE_HERO` 分别管正文 / 按钮 / 主操作字号。
- **QSS 模板**：`line_edit_qss` / `combo_box_qss` / `check_box_qss` / `card_qss` / `menu_qss` / `message_box_qss` / `scroll_area_qss` 等，全部 f-string 插值 token。
- **按钮风格（平面化）**：主按钮 `primary_button_qss`（钢蓝纯色底 + 白字，hover/pressed 转深空蓝）；次级 / 危险 / chip 共用 `outlined_qss`（透明底 + 圆角边框，hover 只变边框/字色、不填背景）。
- **按钮工厂**：`make_pill_button` / `make_secondary_button` / `make_icon_button` 统一构造入口，替代各文件手写 `QPushButton` + `setStyleSheet`。

**平面风格约定**：不使用阴影（`QGraphicsDropShadowEffect` 已移除）；背景 `BG_MAIN` 极淡蓝、卡片 `BG_CARD` 白；标题栏颜色经 `sync_titlebar_color(widget, theme.BG_MAIN)`（在 `utils.py`）与 DWM 同步。

`dialogs._FormDialogBase` 复用基类样式常量与 `_make_footer(primary_text, slot, *, left_widgets=())`（构造 `[left_widgets…] — [取消] [主按钮]` 行），`SingleScriptConfigDialog` / `AddScriptDialog` 共用。`INPUT_FIXED_W=320` / `INPUT_FIXED_H=30` 统一输入框尺寸，表单用 `QGridLayout`（label 列固定宽、input 列固定宽）保证对齐。

## 写盘架构（单一路径）

**config.yml 写入权统一归 ChainService。** MainWindow / SingleScriptConfigDialog 均不直接写盘。

| 操作 | GUI 触发 | 写盘路径 |
|------|----------|---------|
| 编辑脚本字段 | 弹窗 `save_data` → 存 `pending_changes` → `_on_script_config_saved` | `ChainService.update_script`（内部处理 config + weekly） |
| 增删脚本 | `_add_script` / `_delete_script` | `ChainService.add_script` / `remove_script`（内部处理 config + weekly） |
| 重排 | 拖拽 | `ChainService.save_config` |
| 运行 | 点「运行」 | `ChainService.generate_chain` → `chain_gen` |

`SingleScriptConfigDialog.save_data()` **不再写盘**，仅收集表单数据存入 `self.pending_changes`。ScriptItem `accept` 后将 `pending_changes` 传给 `MainWindow._on_script_config_saved`，后者委托 `ChainService.update_script()` 原子完成 config + weekly 落盘，再重新 `load_config()` 同步内存与卡片。

## 运行流程

点「运行」→ `_generate_config("today")` → `ChainService.generate_chain` → `chain_gen.generate_chain_config` 生成 `config/script_chain/today.yml`（仅含启用的脚本）→ `ScriptChainRunner(QThread)` 以**单个 runner 子进程**运行整条链。

命令：开发态 `python -m src.runner.launcher --chain <path>`（注入 `PYTHONPATH=src/runner`）；frozen 态用同目录 `OneDragon-Helper-Runner.exe`。链内每条脚本的 `block` 字段决定阻塞/非阻塞（缺字段视为阻塞），详见 [`src/runner/README.md`](../runner/README.md)。

## UI 状态持久化

`gui_state.json` 只存 `dungeon`/`sequence`（用户选了哪个副本）。`enabled`（开关）是纯内存态，重启恢复全开。经由 `ChainService.load_ui_state` / `save_ui_state` 读写。
