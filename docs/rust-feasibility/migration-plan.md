# Rust GUI 渐进迁移计划

2026-09-28。近期路线：Rust 接管全部现有 GUI，助手业务保留 Python CLI。
每块以可独立验收的 PR 交付，完成一块即测试、提 PR、继续下一块。

## 当前基线

- #97 的任务卡 service、#100 的资源声明、#101 的无 Qt CLI、#104 的显式配置初始化、
  #105 的 CLI 原接口转发均已合入 main。
- [#103](https://github.com/LevelDownRefine/OneDragon-Helper/pull/103)（`codex/rust-gui-prototype`）
  已重接 `main@1573bfc`；只保留 Rust 前端、资源、开发工具、测试与 CI。
- #102 的 Qt CLI 测试模式独立保留，不是 Rust 的运行或合并依赖，本轮不修改该分支。
- CLI 日常响应为 `name/task/sequence/enabled/options`，周常为
  `name/task/options/start_day`。四个写操作返回 `null`；客户端随后查询 `script.view`，
  分开处理写入失败与刷新失败，不因反读失败重放写入。
- 当前 Rust 可用：原版布局、任务卡分级菜单、日常/周常保存反读、脚本切换、
  连接诊断、窗口拖动/最小化/关闭。其余入口保持“暂不可用”直到对应 PR 接通。
- E [#106](https://github.com/LevelDownRefine/OneDragon-Helper/pull/106) 已接通官网、B 站、GitHub、
  脚本目录、日志及配置文件入口；`codex/rust-gui-navigation` 基于 #103，使用 `script.target`。
- F [#107](https://github.com/LevelDownRefine/OneDragon-Helper/pull/107) `codex/rust-gui-script-config`
  基于 #106，接通单脚本配置表单与 Windows 文件选择；
  `script.edit_view/edit_save` 沿用显式初始化边界，部分失败保留草稿、重新读取后方可再次保存。
  新增 `launcher-rust.bat` 便于从仓库或 worktree 双击测试。
- G [#108](https://github.com/LevelDownRefine/OneDragon-Helper/pull/108) `codex/rust-gui-script-list`
  基于 #107，接通脚本/快捷方式添加、删除确认、拖动排序，
  以及手动勾选、全选/清空。手动状态按脚本身份保留在内存，后台拒绝过期排序。
- H1 [#109](https://github.com/LevelDownRefine/OneDragon-Helper/pull/109) `codex/rust-gui-launch-current` 基于 #108，接通当前脚本/游戏启动；Python 解析目标，
  Rust 通过系统关联或现有 Runner CLI 发起，关闭 GUI 不终止外部进程。
- H2 [#110](https://github.com/LevelDownRefine/OneDragon-Helper/pull/110) `codex/rust-gui-run-batch` 基于 #109，接通批量确认/选项与独立无 Qt 调度入口；
  stdin 传运行载荷，取消不保存、部分失败不启动，GUI 关闭保留运行进程。
- H3 [#111](https://github.com/LevelDownRefine/OneDragon-Helper/pull/111) `codex/rust-gui-shutdown` 基于 #110，接独立 Rust 关机倒计时并开放运行选项。
  只有显式确认码才执行关机；取消/异常/缺入口均不关机，Rust 路径不回退 Qt。
- I1 [#112](https://github.com/LevelDownRefine/OneDragon-Helper/pull/112) `codex/rust-gui-settings` 基于 #111，接全局设置、独立保存运行选项与启动倒计时；
  嵌套保存保留父表单草稿，取消不写盘，每日计划开启/更新后重启/演示模式跳过自动启动。
- I2 [#113](https://github.com/LevelDownRefine/OneDragon-Helper/pull/113) `codex/rust-gui-daily-plan` 基于 #112，接每日计划表单、独立选项与系统任务回读。
  计划入口改为无 Qt CLI daily，保存会修复旧入口；写盘失败恢复原任务 XML，取消保留父草稿。
- J [#114](https://github.com/LevelDownRefine/OneDragon-Helper/pull/114) `codex/rust-gui-backup` 基于 #113，接 ZIP 备份/恢复确认和后台任务轮询；
  保留本机游戏路径、恢复前备份、部分失败详情，处理中不允许普通关窗打断写入。
- K1 [#115](https://github.com/LevelDownRefine/OneDragon-Helper/pull/115) `codex/rust-gui-file-drop` 基于 #114，接整窗脚本/快捷方式拖入、串行添加和结果汇总；
  Windows 使用 WM_DROPFILES 并按窗口放行跨权限消息，部分写入失败停止后续导入、刷新核对。
  原生图标和悬停预览留给 K2。
- K2 [#116](https://github.com/LevelDownRefine/OneDragon-Helper/pull/116) `codex/rust-gui-native-icons` 基于 #115，接 Windows 脚本图标与游戏悬停预览；
  Python 仅解析路径，Rust 异步提取内嵌图标、恢复透明度、缓存并显示；刷新失效缓存，失败回退图标/文字。
- L1 [#117](https://github.com/LevelDownRefine/OneDragon-Helper/pull/117) `codex/rust-gui-image-wallpaper` 基于 #116，接默认/自定义图片壁纸与恢复默认；
  Rust 有界异步解码 PNG/JPEG/WebP/BMP，Python 保存映射和缩图缓存，切换丢弃旧结果。
  视频暂显示原版首帧缓存或渐变占位，播放留给 L2。
- L2 [#118](https://github.com/LevelDownRefine/OneDragon-Helper/pull/118) `codex/rust-gui-video-wallpaper` 基于 #117，接 Windows 系统解码、静音循环、500ms 延迟播放；
  首帧仍经 CLI 写缓存，切换/退出释放后台资源，失败保留已有画面或渐变并提示。
  使用系统 Media Foundation，格式支持取决于已安装的编解码器；不附带 Qt/FFmpeg 播放库。
- M1 [#119](https://github.com/LevelDownRefine/OneDragon-Helper/pull/119) `codex/rust-gui-update` 基于 #118，接版本/上次结果、显式检查、说明、下载进度和取消；
  发布对象与准备好的目录留在 Python 会话，RPC 不接受任意下载 URL 或包路径。
  安装与重启暂不可用，留给 M3 验证 GUI/CLI 双进程交接。
- M2 [#120](https://github.com/LevelDownRefine/OneDragon-Helper/pull/120) `codex/rust-gui-update-package` 基于 #119，区分 Qt/Rust 发布附件、清单与版本元数据；
  Rust 包要求独立 CLI、不要求 QML，缺少类型的历史包仍按 Qt 处理。
  下载、安装交接与事务均拒绝跨类型替换；正式 Rust 包构建留给 N。
- M3 [#121](https://github.com/LevelDownRefine/OneDragon-Helper/pull/121) `codex/rust-gui-update-install` 基于 #120，开放显式安装与就绪后退出；
  双进程身份与父子关系核验、统一退出期限、同目录 CLI 任务识别，失败保留窗口供重试。
  源码模式仍不支持原位更新；正式 Rust 包及双进程真实 EXE 交接留给 N 验证。
- N1 [#122](https://github.com/LevelDownRefine/OneDragon-Helper/pull/122) `codex/rust-gui-package-cli` 基于 #121，构建独立无 Qt CLI，并加入真实 Windows EXE 测试；
  仅后端组件，完整 GUI 入口、UAC、发布布局和双进程升级在后续 N 批次接入。
- N2 [#123](https://github.com/LevelDownRefine/OneDragon-Helper/pull/123) `codex/rust-gui-packaged-entry` 基于 #122，Rust 从 EXE 所在目录读取包身份并直接运行随附 CLI；
  开发路径显式保留，损坏/缺失后端不回退 Python。真实临时组装目录在无源码、无 Python PATH、
  外部工作目录条件下显示任务卡；UAC、完整发布资源和双进程升级继续由后续 N 批次完成。
- N3 [#124](https://github.com/LevelDownRefine/OneDragon-Helper/pull/124) `codex/rust-gui-cli-entry` 基于 #123，原 `--version/--selftest/--schedule-run` 等 CLI 参数
  经 Rust 转交无 Qt 后端，保留输出文件和退出码；独立 CLI EXE 同样支持原参数。
  未指定动作或非法参数直接失败，不回退 Qt；冻结入口默认使用同目录 Rust 关机确认窗。
- N4 [#125](https://github.com/LevelDownRefine/OneDragon-Helper/pull/125) `codex/rust-gui-release-resources` 基于 #124，让发布资源工具生成和校验 Rust 清单；
  必须包含独立 CLI、排除 QML，用户配置边界不变；共用的 EXE 升级夹具保留实际包类型。
  完整构建、UAC 和 Windows CI 产物接入下一批。
- N5 `codex/rust-gui-release-build` 基于 #125，独立构建 Rust GUI/CLI/Runner/Updater、
  给发布 GUI 写图标与管理员 manifest、归档并接入 Windows 完整 EXE CI 与 tag 发布。
  输出仅限仓库 dist，拒绝覆盖运行过的安装；构建临时目录独立，保留 Qt 构建。
  双进程真实更新交接与完整包对比继续单列验收。
- 本轮基线验证：Ubuntu 1155 项（1121 通过、34 项原有跳过）；Rust 13 项，
  含真实 CLI 与写确认后刷新失败不重放；Ruff、rustfmt、严格 Clippy。

## 连续 PR 顺序与验收

以下是 #103 之后的功能批次，每批同时带必要的 CLI 薄接口、Rust 界面和测试。
接口名是候选设计，以各 PR 的最终实现为准；不单独堆一个“所有后端接口”大 PR。
原版 GUI 继续可用，Python 配置/路径/任务语义沿用现有 service 和机制类。

| 批次 | 用户功能 / 对照源码 | 边界与关键验收 |
| --- | --- | --- |
| E：工具栏导航 | `controllers/links.py` 的官网、B 站、GitHub、脚本目录、日志、配置文件 | Python 经资源声明和现有解析器返回明确的 URL/路径/不可用原因；Rust 用系统关联打开，错误可见。无脚本、未适配、文件缺失和带空格/中文路径有测试；不把打开文件用作启动游戏接口 |
| F：脚本配置 | `dialogs.py` 的路径、参数、超时、完成条件、游戏路径、七日周常超时、原生任务开关 | 读取/保存经 CLI；Rust 保留表单草稿和错误。保存按 `update_script → init_script_after_edit → set_script_switches`，保留 #104 的初始化边界；取消不写盘，路径/身份变化和部分失败可解释 |
| G：脚本列表 | `controllers/game_list.py` 的添加、删除、重排、手动勾选、全选/清空、控制模式 | CLI 复用 `build_script_entry/add_script/remove_script/save_config`；保留脚本身份与顺序；手动勾选只存内存、重启全选，每日计划独立。添加与快捷方式解析只记录信息，不运行脚本；重复/失效路径明确提示 |
| H：运行与运行选项 | `controllers/launch.py`、`run_confirm_dialog.py`、`run_options_editor.py` 的当前/全部运行、确认、静音/恢复、失败重跑、通知、关机选项；工具栏启动游戏 | 长链以独立调度/Runner 进程运行，不阻塞 stdio；GUI 退出不终止正在运行的链。Python 负责校验、命令和业务；Rust 管确认与显示。凭据不写日志/命令行，游戏启动独立验证；关机确认以独立 Rust 入口替换隐式 Qt 弹窗后才启用 |
| I：启动与每日计划 | `config_dialog.py`、`startup_dialog.py`、`daily_plan_dialog.py` 的自动启动倒计时、保存/取消、每日时间与独立运行选项、系统任务状态 | 计划继续由 Python 注册与回读，指向可无 GUI 运行的入口；手动勾选不影响每日计划，暂停保留设置，任务注册失败不留下不一致配置。自动启动、每日计划与更新后跳过倒计时保持原行为 |
| J：备份恢复 | `controllers/backup.py` 的备份 ZIP、恢复选择、覆盖确认、结果提示 | 复用 `create_backup/restore_backup`，保留本机游戏路径、恢复前 ZIP、部分成功和跳过原因；取消不改配置，用临时目录测试，不操作真实备份 |
| K：原生图标和拖放 | `icons.py`、`file_drop.py` 的脚本/游戏 EXE 图标、悬停预览、文件和快捷方式拖入 | Rust 提取/缓存图标、处理文件拖入；Python 解析目标和参数。兼容管理员窗口，多文件统一汇报，不误启动文件；缩放和图标缺失有回退 |
| L：壁纸 | `controllers/background.py`、`qml/background.qml` 的脚本默认背景、图片/视频、自定义选择/重置、首帧缓存 | Python 解析资源与保存映射/缓存；Rust 解码播放与呈现。覆盖切换脚本、静音/循环、首帧未就绪、缺失媒体、退出释放文件；不借用 Python Qt 播放器冒充迁移完成。视频依赖及体积在该 PR 明示 |
| M：手动更新 | `controllers/update.py`、`update_dialog.py` 的版本/说明、检查、下载进度、取消、安装重启、上次结果 | 复用现有 Python 更新事务；先定义有界后台任务、轮询/进度与取消协议。确认 Rust GUI、CLI 和更新器的身份/运行锁、就绪后退出、失败重试与安装后重启；不修改 runner 子模块 |
| N：完整入口与发布验证 | `launcher.py` 与打包/EXE 测试的入口、UAC、运行锁、重启参数 | Rust GUI + 无 Qt Python 后端能独立分发；关机/每日计划/更新不回退 Qt。验证安装布局、源代码/冻结根路径、后端缺失提示、资源清单、升级和退出；再测同条件体积与启动时间 |

F/G、H/I、K/L 分开，使配置保存、运行调度和媒体平台代码能单独审查。
若某一块超出单次可审查范围，按已可用的用户操作继续拆小，不以隐藏入口或模拟响应代替完成。
每个 PR 描述写清已实现与剩余功能，并更新本表中的实际 PR 链接。

## 分支与合并

```mermaid
flowchart LR
    M["main · Python service + CLI"] --> D["#103 · Rust 任务卡"]
    D --> E["E · 导航"] --> F["F · 配置"] --> G["G · 列表"]
    G --> H["H · 运行"] --> I["I · 启动/计划"] --> J["J · 备份"]
    J --> K["K · 图标/拖放"] --> L["L · 壁纸"] --> U["M · 更新"] --> N["N · 发布"]
```

先以相邻前置分支作为 PR base，让每个差异只包含本批改动；不用等待人工逐项确认才继续。
前置 PR squash 合并后，子分支用 `rebase --onto` 跳过旧前置提交并转到 main，
保留测试与实际功能差异。CI 对 main/master 和 `codex/rust-gui-*` 目标分支运行。
不替用户自动合并 PR，也不同时改动已有的 Qt 分支。

## 统一完成条件

- 声明来自 `script_resources.yml`、日常/周常/任务开关声明及用户配置；Rust 不复制业务表。
- 所有配置写入经 service/CLI，Rust 保留交互状态与草稿。界面关闭、Esc、取消不触发保存。
- 快请求沿用串行 JSONL；运行、下载、取消另有明确生命周期，不能用增加超时掩盖阻塞。
- 保留整数/布尔/字符串、未设置/不启用等现有语义；失败不静默，不自动重复写操作。
- 每批跑 Ubuntu Python 全量与 Ruff、Rust fmt/Clippy/测试；用真实临时配置和无 Qt 导入守卫
  验证 CLI。界面截图检查布局，输入测试检查交互；源码测试与 Windows 打包验证遵循 TESTING.md。
- N 之后才比较完整安装目录、压缩包和外部依赖；同机同配置测首帧/可操作时间，区分冷/热启动。
  单独的 Rust EXE 大小不是完整助手体积，未验证前不报告加速百分比。

旧拆分参考：#97 → #101 → #102/#103。原始引用保存在
`codex/pr97-before-split-20260927@a79c4b2` 和 `codex/rust-gui-before-split-20260927@f1c0572`；
此次 rebase 前本地引用为 `codex/rust-gui-before-rebase-20260928@67ca010`。
