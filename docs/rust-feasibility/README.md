# Rust 迁移的体积与启动效率评估

日期：2026-09-26。基线：本地 `main`，`71bc7c5495de94261f48be8005ac022511c7d50a`；
分支：`codex/rust-feasibility`；Runner：`de44e4d6efab0c61443184635c81e018e021652b`。
没有把当前增量更新分支的变更带入评估，也没有用 `origin/main` 替换本地 `main`。

后续已选定近期路线：**Rust GUI + 保留助手业务为 Python CLI，逐步迁移**。
调用审计、缺失接口和实施顺序见 [GUI / CLI 边界设计](gui-cli-boundary.md)。
本报告下文的完整 Rust 迁移公式是远期方案，不能直接当作近期阶段的体积预测。

外部 Python 脚本支持已确定走 CLI；下文全 Rust 方案按“脚本侧提供所需 Python 环境”
计算，旧版进程内 `exec` 不作为必须保留的实现。近期助手自己的 Python CLI 环境仍需保留。

## 判断

**Rust 可以消除 Python 解释器、模块导入和绑定层的一部分成本，但收益取决于迁移边界。**
本项目主要负责配置读写、GUI 和外部进程编排，游戏自动化实际由外部 EXE 执行。
改写助手不会让这些外部程序的识别、战斗或加载变快。

- **保留 PySide6，只把 service 改为 Rust：** Python、Qt 和绑定层仍在，整体体积/首帧收益有限，新增桥接还有额外成本。
- **主程序全部改为 Rust，保留 Qt/QML：** 可去掉主程序中的 Python 运行时和绑定层，体积有中等幅度的优化空间；Qt、QML、视频解码和窗口初始化成本仍在。
- **Rust 同时替换界面框架：** 才有机会进一步移除 Qt 的大块依赖。需要重写界面，Tauri 的系统 WebView2、其他框架的渲染器和视频支持必须计入比较。
- **只迁移 Runner/Updater：** 缩小相应 EXE、减少其单文件解压成本；这两个程序不在普通 GUI 首帧路径上，不能据此声称主窗口更快。

**建议先精简当前打包依赖并补发布 EXE 的端到端基线，再决定是否完整迁移。**
在 Python 脚本已确定走外部 CLI 的前提下，若希望引入 Rust，可优先做 Runner 原型，
验证外部进程编排与构建/部署链，再迁移独立更新器；
若重点是主窗口启动，则应直接比较保留现有 QML 的 Rust/Qt 原型与优化后的 Python 版本。
本次未实现同功能 Rust 版本，因此下列 Rust 收益是结构性推断和预算公式，不是迁移后的实测成绩。

## 当前版本的体积实测

Windows x64；共享开发环境 CPython 3.12.10（conda）、PySide6 6.8.0.2、
PyInstaller 6.19.0、contrib hooks 2026.4。按 `main` 的三个原始 spec 重新构建，
未改打包规则，未启用 UPX。使用 `release_package.py prepare/check/archive` 整合、校验和归档。
这是本机开发包的结果；构建环境、依赖及压缩方式变化会改变发布体积。

总计 **298 个文件，152.17 MiB**；发布 ZIP **77.15 MiB**。
MiB 为 1,048,576 字节，目录体积按文件内容求和，不是磁盘分配大小。
没有把开发环境 `.venv`、构建缓存或根目录下重复的 Runner/Updater 计算进去。

| 互斥分类 | MiB | 比例 | Rust 迁移的影响 |
| --- | ---: | ---: | --- |
| Qt 原生库、QML、插件 | 45.64 | 30.0% | 保留当前 Qt 功能和部署集合时仍需携带 |
| FFmpeg 视频解码库 | 17.25 | 11.3% | 保留当前视频后端时仍需携带 |
| PySide6 / Shiboken 绑定 | 26.84 | 17.6% | 主程序完整脱离 Python 后可移除 |
| CPython DLL 与标准库 ZIP | 8.39 | 5.5% | 主程序完整脱离 Python 后可移除；不含两个 onefile 中的重复运行时 |
| GUI EXE（含 Python 模块归档） | 9.34 | 6.1% | 由 Rust EXE 和其依赖替代，不能把全额当作净节省 |
| Runner onefile | 10.31 | 6.8% | 外部 CLI 方案下可整体替换，不再内嵌 Python |
| Updater onefile | 8.73 | 5.7% | 单独迁移；保持事务/回滚/锁协议 |
| 应用资源、模板和清单 | 1.34 | 0.9% | 语言改变不会自动消除 |
| 其他原生扩展、库和数据 | 24.31 | 16.0% | 含 OpenSSL、Python/Windows 扩展及运行库，需逐项核对，不能一律视作可删 |

原始字节数、逐文件分类、包版本和启动样本见 [measurements.json](measurements.json)。
分类把 `_internal/PySide6` 中的 `.pyd` 和绑定 DLL 归入绑定，其余非 FFmpeg 文件归入 Qt 类；
它是部署文件清单分类，不是程序运行时的内存或依赖调用图。

### 可以支撑的量化结论

只替换主程序、保留当前 Qt/视频库和两个 Python 辅助 EXE 时：

```text
当前包                                        152.17 MiB
移除 GUI EXE + 主 Python 运行时 + PySide 绑定    -44.58 MiB
先保留其他文件后的基数                         107.59 MiB
迁移后体积 = 107.59 MiB + R - D
```

`R` 是 Rust 主程序及新增依赖体积；`D` 是进一步确认可从“其他”分类移除的体积，
范围至多 0～24.31 MiB，不能预设为全部可删。当前 Qt/视频、应用资源及两个辅助程序
合计 **83.28 MiB**；在这组依赖保持不变的前提下，它们构成固定负担。
因此，44.58 MiB 是被替代层的毛体积，既不是最终净节省，也不是所有迁移路线的收益上限。

只迁移更新器，净收益为 `8.73 MiB - Rust 更新器及新增依赖`；
只迁移 Runner，相应为 `10.31 MiB - Rust Runner 及新增依赖`。
两个辅助程序都迁移时，合计可替代的现有文件为 **19.04 MiB（整包约 12.5%）**，
净节省仍须减去两个 Rust 产物及新增依赖。Python CLI 的环境归脚本侧，
不计入助手分发包，但在新机器的总安装成本比较中应单列，不能称为“系统不再需要 Python”。
这些公式比较解包后的目录，**不能直接套用到 ZIP 大小**；当前 onefile 已有内部压缩。

若主程序、Runner、Updater 全部迁移为 Rust，同时保留当前 Qt/视频部署集合：

```text
迁移后体积 = 88.55 MiB + R_all - D
           = 64.24 MiB 的现有 Qt/视频/应用资源
             + 保留下来的其他依赖 + 全部 Rust 产物及新增依赖
```

这里可替代的原 Python 主程序层及两个辅助 EXE 合计 **63.62 MiB（41.8%）**，
仍是毛体积。用户已确定的外部 CLI 边界使这条路线无需在助手包中保留 Python 解释器；
最终净节省取决于 Rust 实现和依赖清单。本公式不覆盖进一步裁剪 Qt 模块或换 GUI 框架的方案。

Rust/CXX-Qt 可以提供 QObject 与 QML 之间的桥接，但仍使用 Qt；
Qt 的部署要求包含所需共享库、QML 和资源。[CXX-Qt 文档](https://kdab.github.io/cxx-qt/book/)、
[Qt 部署文档](https://doc.qt.io/qt-6/cmake-deployment.html)。

Tauri 可使用系统 WebView2，从应用分发包中移除 Qt/PySide 等依赖，因此有更大减重潜力。
但“小下载包”不等于“机器上没有浏览器运行时”：官方文档给出的离线安装器额外开销约
127 MB，固定版 WebView2 约 180 MB，且随版本变化。若要求全离线、自带全部运行时，
必须将它们算入安装器比较；这些 MB 数字不是本项目的新包实测值。
[Tauri Windows 安装文档](https://v2.tauri.app/distribute/windows-installer/#webview2-installation-options)。

Slint 等原生 GUI 路线也需选定具体 backend/renderer 后实测；渲染器选择会改变依赖，
当前视频壁纸能力还需要单独验证。[Slint 渲染后端文档](https://docs.slint.dev/latest/docs/slint/guide/backends-and-renderers/backends_and_renderers/)。

## 启动实测与边界

使用 [measure_startup.py](measure_startup.py)，一次预热后 15 次独立进程。
临时复制新工作树内的模板、资源和 QML，设置空脚本列表，使用 `--after-update`，
在 `QQmlApplicationEngine.objectCreated` 时连接首个 `frameSwapped`。
测量期间无本次打包任务并行运行，不读取真实脚本配置、不运行游戏、不清理用户全局 QML 缓存。

| 源码场景指标 | 中位数 | 最小～最大 |
| --- | ---: | ---: |
| 父进程启动子 Python 到首帧 | **436.55 ms** | 426.28～453.89 ms |
| 子进程依赖导入开始到首帧 | **354.68 ms** | 344.00～367.24 ms |
| 进程启动到探针开始（含解释器、标准库和参数解析） | 79.78 ms | 74.90～86.65 ms |
| 探针先行导入 Qt 等 | 68.32 ms | 63.57～73.89 ms |
| launcher 追加导入 | 155.03 ms | 149.71～163.63 ms |
| 调用 main 到首帧 | 131.11 ms | 125.70～134.69 ms |

分项是各自中位数，相加不必精确等于总时间。Qt 先行导入是为安装测量钩子，
与真实入口的导入次序不同；约 223 ms 的导入时间包含 Qt DLL、Python 绑定及业务/GUI 模块，
不能解释成“223 ms 的 Python 运算”，更不能认定 Rust 会全部消除。

本次是 **offscreen、文件缓存已预热、空脚本列表的源码基线**。
未测真实显卡窗口的呈现/输入响应、完整安装脚本列表、视频首帧、首次安装、
重启后的冷启动、UAC 交互、PyInstaller bootstrap 与运行锁。
它可以定位当前源码加载成本，不能替代用户点击发布 EXE 后可操作的时间。
也没有使用已有源码优化实验的旧成绩来计算本次收益。

源码可见的改进机会：

1. `src/launcher.py` 在 CLI 分流前顶层导入 Qt 和 GUI；Rust CLI 可以避免这部分成本，Python 同样可以延迟导入。
2. 当前入口禁用 QML 磁盘缓存并清理旧缓存。需先解决原有缓存一致性问题，再评估按版本隔离缓存或构建期预编译；不能直接删除防护。
3. `requests` 已在手动更新时延迟导入，不能再次把这项已经实现的收益算给 Rust。
4. 常规 GUI 首帧不启动 Runner/Updater；它们迁移带来的进程创建收益出现在点击运行/安装更新之后。

GUI 是 `onedir`；Runner 和 Updater 是 `onefile`。单文件启动需展开支持文件，
这是后两者迁移到原生 EXE 可减少的一类成本，GUI 不具有同样的整包展开路径。
[PyInstaller 工作原理](https://pyinstaller.org/en/stable/operating-mode.html#how-the-one-file-program-works)。
Qt 的构建期 QML 编译可以避免运行时重复编译，但这是构建/加载策略的收益，
不能全归因于 Rust。[Qt Quick Compiler](https://doc.qt.io/qt-6/qtqml-qtquick-compiler-tech.html)。

## 改造成本及兼容性

当前主仓 Python 67 个文件约 15,631 行，Runner 30 个文件约 4,939 行，
QML 5 个文件约 1,680 行；均为物理行，含注释，不能直接换算开发工期。

| 路线 | 可复用部分 | 主要工作与风险 |
| --- | --- | --- |
| Rust 辅助程序 | 当前 GUI、配置服务 | Updater 的路径校验、锁、哈希、替换/回滚协议；Runner 的进程树、超时、中断、控制台和 Windows 音频 |
| Rust + Qt/QML | 主窗口 QML、资源、声明文件 | Python QObject/信号/属性、图标 provider、Widgets 弹窗、service/config/log 仍需迁移；CXX-Qt 不会自动翻译现有 Python 控制器 |
| Rust + 新 GUI | 配置格式、资源、业务契约及测试夹具 | QML/Widgets 交互重做；透明圆角、管理员拖入、快捷方式、中文输入、视频背景、弹窗和更新退出流程需逐项回归 |

迁移时需要落实的行为契约：

- `src/runner/launcher.py --script` 以及 `script_chainer/win_exe/script_runner.py::_exec_python_file`
  目前在进程内执行用户 `.py`。按用户确定的方案，迁移后统一调用外部 CLI，
  因而这项旧实现不再阻碍移除 Runner 内的 Python。需明确 CLI 命令/参数与解释器或脚本入口的来源，
  保持工作目录、环境变量、UTF-8 日志、退出码、超时、取消及子进程树清理的契约；
  环境缺失应明确报告。CLI 调用仍会有脚本侧的解释器启动成本，须计入“任务真正开始”的端到端测量。
  Runner 是独立仓库，正式迁移须在那里单独维护。
- `src/utils/utils_yaml.py` 使用 ruamel 的 round-trip 模式，保留注释、键序、引号及 YAML 1.2 语义。
  Rust 替代实现必须验证同等保真和原子写入，不能仅以“能反序列化”为完成标准。

## 决策顺序

1. **先检查现有 Python 包的冗余。** 主仓与 Runner 源码未发现 `qfluentwidgets`、`pynput` 的实际导入，
   spec 却仍主动全量收集；开发依赖中还保留 OpenCV/NumPy。应逐项移除收集规则并运行 EXE 功能测试。
   NumPy 已被当前 spec 排除，不能再次计算其整个 wheel 的节省；开发依赖也不等于发布依赖。
2. **建立发布 EXE 基线。** 同一机器、同一功能和配置，分别测已预热启动及重启后的首次启动，
   记录进程创建到首帧、到可交互、运行按钮到首个外部进程创建；UAC 的人工等待单列。
3. **再做单一 Rust 原型。** 若优先体积，先按外部 CLI 契约迁移 Runner，再试无 Qt 的 Updater；若优先主窗口延迟，
   试 Rust/CXX-Qt 复用当前 QML。原型必须包含真实配置反读、图标和关键弹窗，空窗口不能代表整个助手。
4. 同时报目录体积、下载包大小、额外共享运行时、同条件首帧/可交互时间及多次运行的分布。
   Rust 使用 release 构建；LTO、strip 和优化级别固定，不拿 debug 产物或纯 hello-world 与现有完整程序比较。
   [Cargo 构建配置](https://doc.rust-lang.org/cargo/reference/profiles.html)。

## 复现与验证

在该提交的干净工作树初始化 Runner，用项目虚拟环境运行；不得用含真实用户配置的目录作为探针输入。

```powershell
# 在 deploy 中按原 spec 构建，再把两个辅助 EXE 复制到 GUI 包目录。
python -m PyInstaller --noconfirm OneDragon-Helper.spec
python -m PyInstaller --noconfirm OneDragon-Helper-Runner.spec
python -m PyInstaller --noconfirm OneDragon-Helper-Updater.spec

# 返回项目根；输出 ZIP 路径自行选择。
python tools/release_package.py prepare --package deploy/dist/OneDragon-Helper
python tools/release_package.py check --package deploy/dist/OneDragon-Helper
python tools/release_package.py archive --package deploy/dist/OneDragon-Helper --output main.zip
python docs/rust-feasibility/measure_startup.py --checkout (Get-Location).Path --output startup.json --runs 15
```

- 三个原始 spec 构建成功；发布资源/清单校验及归档成功。最初沙箱无法读取共享 venv 的包 METADATA，扩展权限重试后完成，未修改依赖或 spec。
- `ruff check src tests tools` 与 `ruff format --check src tests tools` 通过。
- Ubuntu 全量 `PYTHONPATH=src python -m unittest discover -s tests -t . -p "test*.py"`：1076 项，1042 项通过、34 项跳过，47.30 秒。
- 上述测量阶段仅新增评估文档、测量数据和实验探针，未修改应用/Runner/打包逻辑；探针实际完成 16 次启动（含 1 次预热），数据总量/分类和样本数一致性校验通过。未运行管理员 EXE 集成测试；构建成功不代表 EXE 行为已回归。
- ZIP SHA-256：`dcfcf9d0adc3fcf6325ed2bb810cdaec95abbfe328833f946578012dd03a9b3a`。ZIP 时间戳等会使重新归档的哈希变化。

后续已实现 [无 Qt CLI 的首条任务卡闭环](headless-cli.md)，以保留 Python 业务、逐步迁移为边界。
上面的体积与启动测量仍属于原始 main 基线，不是新 CLI 或 Rust 版本的测量。
