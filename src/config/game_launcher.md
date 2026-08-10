# game_launcher — 打开各脚本对应游戏（调研/设计稿）

需求：GUI 里为各自动化脚本提供一个「打开游戏」入口，点击后启动该脚本对应的游戏。

核心结论：**本项目不维护游戏路径**，各自动化脚本自己的 config 里已经存了游戏 exe 路径，直接读即可。

> **定位（用户拍板 2026-08-10）**：这是 GUI 里额外集成的小功能，**不涉及脚本链任何内容**。真跑脚本链时用不到它，无需在 chain / runner / ScriptChainConfig 层面做任何适配。

## 调研结论：各脚本游戏路径位置（实测 2026-08-10）

| 脚本 | 游戏 | 配置文件（相对脚本根） | 字段 | 启动方式 |
|------|------|----------------------|------|---------|
| 鸣潮 | 鸣潮 | `data/apps/ok-ww/working/configs/devices.json` | `pc_full_path` | exe 直启 |
| 终末地 | 终末地 | `data/apps/ok-ef/working/configs/devices.json` | `pc_full_path` | exe 直启 |
| 异环 | 异环 | `data/apps/ok-nte/working/configs/devices.json` | `pc_full_path` | exe 直启 |
| 原神 | 原神 | `User/config.json` | `genshinStartConfig.installPath` | exe 直启 |
| 绝区零 | 绝区零 | `config/01/game_account.yml` | `game_path` | exe 直启 |
| 崩铁 | 崩铁 | `config.yaml` | `game_path` | exe 直启 |
| 粥 | 明日方舟（MuMu 模拟器） | `config/gui.new.json` | `Gui.StartUpSettings.EmulatorPath` | `.lnk` 快捷方式 |

实测路径示例（仅记录格式，机器不同会变）：
- 鸣潮：`D:\Wuthering Waves\Wuthering Waves Game\Client\Binaries\Win64\Client-Win64-Shipping.exe`
- 原神：`D:\miHoYo Launcher\games\Genshin Impact Game\YuanShen.exe`
- 崩铁：`D:\miHoYo Launcher\games\Star Rail Game\StarRail.exe`
- 粥：`C:\Users\WinSa\Desktop\#0 MuMu安卓设备.lnk`

### 关键观察

1. **游戏路径文件 ≠ 副本配置文件**。`subscript.py` 的 `_CONFIG_REL_PATHS` 指向副本 config（鸣潮/终末地/异环的 `DailyTask.json`、原神的 `User/OneDragon/默认配置.json`、绝区零的 `charge_plan.yml`），**不是**游戏路径所在文件。仅崩铁（`config.yaml`）、粥（`gui.new.json`）两者同文件。
2. **JSON / YAML 两种格式都有**。`subscript.load_config` 已按扩展名分派解析，可复用。
3. **字段结构差异大**：OK 系是顶层 `pc_full_path`；原神是二级嵌套 `genshinStartConfig.installPath`；绝区零/崩铁是顶层 `game_path`；粥是三级嵌套 `Gui.StartUpSettings.EmulatorPath`。
4. **粥的路径是 `.lnk` 快捷方式**，不是 exe。`os.startfile` 对 exe 和 lnk 都适用，是最通用的启动方式。

## 实现思路

### config 层

类似 `_CONFIG_REL_PATHS`，新增一张 `_GAME_PATH_REL_PATHS: dict[str, str]`（脚本 → 游戏路径配置文件相对路径）。但字段提取逻辑各脚本不同，宜走 `set_config.py` 的类层级：每个子类实现 `get_game_exe_path() -> str`，基类提供默认（读 `_GAME_PATH_REL_PATHS` 映射的配置文件，按子类指定的嵌套路径取值）。

```python
class ScriptConfig:
    _game_config_rel_path: str = ""   # 游戏路径所在配置文件相对路径
    _game_path_json_path: list[str]   # JSON 取值路径（如 ["genshinStartConfig", "installPath"]）
    _game_path_yaml_path: list[str]   # YAML 取值路径（如 ["Gui", "StartUpSettings", "EmulatorPath"]）

    def get_game_exe_path(self) -> str | None:
        """读脚本 config，返回游戏 exe 路径；无适配/文件缺失/字段缺失时返回 None（不 assert）。"""
```

- 只读不改写，`enabled` 标记、`_confirm_save` 等写流程不参与。
- 缺失时应返回 `None` 而非 assert（脚本可能换路径/文件损坏，GUI 要优雅降级）。这符合 AGENTS 第 1 条：这是「可恢复情况」，不是「不该发生的编程错误」。

### GUI 层（已定稿 2026-08-10）

**采用方案 2：图标右键菜单。** 左键=启动脚本（现状不变），右键弹「打开游戏」。侵入最小，不改变现有卡片布局，无新增按钮。

`ScriptItem` 卡片当前横向布局（保持不变）：

```
[icon] [title]  |stretch|  [dungeon_btn]  |stretch|  [toggle]
```

已否决的方案：
- ~~卡片内加小按钮~~：改变布局，且 python 辅助脚本不显示时会产生空洞。
- ~~标题旁并排按钮~~：标题宽度由 `_sync_title_widths` 统一管理，并排按钮会干扰等宽逻辑。

实现要点：
- 仅 external 且 `get_game_exe_path()` 返回非空的脚本，右键菜单才出现「打开游戏」；python 辅助脚本不显示。
- `launcher_mode: true` 的脚本（鸣潮/终末地/绝区零/异环）照常读 `pc_full_path` / `game_path` 开游戏本体，与脚本入口职责分离。
- 读取路径是文件 IO，菜单弹出时 try 捕获，失败则该项置灰或提示，不阻塞主流程。
- 测试：`get_game_exe_path()` 各子类用 mock config 覆盖；GUI 菜单显隐逻辑单独可测。

## 实现记录（2026-08-10 完成）

- `subscript.py`：新增 `_GAME_PATH_REL_PATHS`（脚本 → 游戏路径配置文件相对路径，key 为 script_name，exe 即进程名）与 `load_game_config()`（只读查询，文件缺失返回 None 不 assert）；新增 `_get_script_root_dir_soft()`（不校验 exe 存在，供只读查询）。
- `set_config.py`：基类新增类属性 `_game_path_keys`（嵌套键路径）与类方法 `get_game_exe_path()`（不实例化、无写盘副作用）；各子类声明 `_game_path_keys`；新增外观接口 `get_game_exe_path()`。
- 粥的路径实测为 `Configurations.Default.Gui.StartUpSettings.EmulatorPath`（多级嵌套），非顶层 `Gui`。
- `widgets.py`：`_icon_mouse_press` 左键=启动脚本、右键=`_show_game_menu`；菜单构建与弹出分离（`_build_game_menu` 返回菜单或 None，便于测试）。
- 测试：`test_subscript.py` 增 `TestLoadGameConfig`（6 例）；`test_set_config_subclasses.py` 增 `TestGetGameExePath` + `TestGetGameExePathFacade`（10 例）；`test_gui_widgets.py` 增 `TestScriptItemGameMenu`（3 例）。全量 430 通过，ruff 干净。
- 真实环境验证：7 个游戏脚本全部读出真实路径，python/自定义脚本返回 None。
- **后续全局改造（2026-08-10）**：`get_game_exe_path()` 外观入参从 display_name 改为 script_name（exe 用进程名）；GUI `ScriptItem` 用 `script_name` 属性定位，`_build_game_menu` 传 `script_name`。python 脚本的 `script_name` = display_name，不在 `_CONFIGS` 注册表 → 右键不弹「打开游戏」。

## 相关文件

| 文件 | 作用 |
|------|------|
| `src/config/subscript.py` | `_CONFIG_REL_PATHS` / `get_script_name` / `load_config`（复用） |
| `src/config/set_config.py` | `ScriptConfig` 类层级（加 `get_game_exe_path`） |
| `src/gui/widgets.py` | `ScriptItem` 卡片（加按钮） |
| `src/gui/theme.py` | 按钮样式工厂 |
