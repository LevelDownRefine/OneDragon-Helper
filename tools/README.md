# 开发与发布工具

本目录提供源码启动、构建、资源生成与上游同步工具；运行期业务留在后端。

## 启动与构建

`launcher.bat` 经 `run_python_gui.py` 优先加载当前检出的源码；`env.bat` 复用已激活环境或向父目录查找 `.venv`。Rust 启动参数见 [Rust GUI](../rust-gui/README.md)。

| 命令（仓库根目录） | 结果 |
| --- | --- |
| `deploy\build.bat` | Qt 完整包及 EXE 测试 |
| `deploy\build-rust.bat` | Rust 完整包、ZIP 和校验文件 |
| `python tools/build_rust.py --test` | Rust 构建后运行真实 EXE 测试，需管理员 |
| `python -m tools.export_rust_icons` | 从 Qt 图标源生成编译期 `assets/icons/` |

Rust 构建需 Windows、Rust 1.95+、MSVC。Qt 输出 `deploy/dist/OneDragon-Helper`；Rust 输出 `deploy/dist/rust/OneDragon-Helper`，同目录生成 `OneDragon-Helper-Rust.zip`。可用 `--output` 指定其他 Rust 输出目录。

构建仅替换通过文件范围和清单哈希校验的输出；存在用户数据、额外文件或已修改程序时拒绝覆盖。日常安装应解压到独立目录。测试和平台前置见 [测试指南](../docs/TESTING.md)。

## 发布

推送 `v主版本.次版本.修订版本` tag 触发正式发布；手动 dispatch 只构建和测试。发布优先复用同提交、主分支 push 的成功完整构建，运行中最多等待 20 分钟；无法复用时重建并测试，不复用 PR 产物。

`release_package.py` 收集 Git 跟踪的 config、assets、README 和 Qt QML；Rust 不含 QML。编译期 `assets/icons/` 不重复拷贝。独立 CLI、Runner、Updater 随包发布，Rust 包还要求主程序同级 CRT。

`config.yml/schedule.yml/weekly.yml`、壁纸映射和缓存、脚本链、日志及备份不进入安装包，即使误被 Git 跟踪也拒绝打包。缺失的用户 YAML 首次启动从模板生成，已有配置保留。

`version.json` 记录版本、tag、commit 和包类型；正式版本来自 `ODH_RELEASE_TAG`，开发构建为项目版本加提交号。`update-manifest.json` 使用 schema 1，记录逐文件 SHA-256；本地 `.update/` 所有权清单不属于发布资源。

```bash
python tools/release_package.py check --package deploy/dist/OneDragon-Helper
python tools/release_package.py archive --package deploy/dist/OneDragon-Helper --output OneDragon-Helper.zip
```

测试前后及归档前均校验发布范围，归档同时生成 `.sha256`。CI 上传未压缩的发布目录，正式发布重新写版本戳并归档。更新运行机制见 [服务层](../python-backend/src/service/README.md)。

Runner 的冻结 Python 环境只含自身依赖；依赖额外第三方库的脚本应由 BAT 调用自己的环境。

## 副本同步

`sync-tasks.yml` 每天北京时间 11:15 检查鸣潮、异环并开 PR，也支持手动触发。周常不由这两个工具更新。

| 游戏 | 数据来源与维护 |
| --- | --- |
| 鸣潮 | ok-ww 的 ForgeryTask/TacetTask `self.structure` 决定支持范围，正式服数据补无音区名称 |
| 异环 | ok-nte 的 `_ID_RANGE` 等原生任务数据，新增数字占位需人工命名 |
| 原神 | 秘境、地脉花等动态选项读取本地资源；首领名单等静态项手工跟版 |
| 终末地 | 读取 ok-ef 本地 world_map.json |
| MAA | 普通关卡静态维护，活动读取本地 StageActivityV2.json |
| 崩铁、绝区零 | 按声明及本地资源提供，不由该 Action 同步 |

```bash
python tools/sync_okww_tasks.py --apply
python tools/sync_oknte_tasks.py
```

退出码：0 无差异或已应用；1 有差异待应用；2 上游抓取/解析暂不可用。上游数量回退只报告，不删除配置。鸣潮凝素领域新增时旧 physical_name 后移、前方补占位，需人工命名。

### 鸣潮无音区

1. 首次接入或 ok-ww 分组相对 `okww_tacet_state.json` 改变时才查询名称；资料站单独更新不推动配置。
2. 从 [Arikatsu/WutheringWaves_Data](https://github.com/Arikatsu/WutheringWaves_Data) 同一提交读取 `BinData/adventure_detect/silentareadetection.json` 和中文 `MultiText.json`：筛选 Secondary=22，按 Name 关联文本、SortId 降序排序。今州同值项沿用已核对的 F2 顺序，其他排序冲突停止同步。
3. 总数与 DetectionTabType 分组须完全匹配 ok-ww，名称完整唯一、旧副本 ID 相对顺序不变。display_name 去掉「无音区」，保留Ⅰ/Ⅱ等区分标记。
4. 同时更新任务声明和状态，PR 附完整编号、名称及来源提交供核对。状态仅存分组、稳定 ID、版本和来源，不重复保存名称。

上游未就绪时整次鸣潮同步暂缓，保留配置和状态，下次重试；异环独立继续。Action 用一次 `--apply --github-output ... --report ...` 获取并应用同一快照。写入先暂存，再替换配置，最后发布状态；本地 I/O 失败须使 Action 失败，不能按上游暂缓跳过。

## 测量

`measure_gui_startup.py` 在临时完整包中测量首张任务画面回读；命令、条件与历史结果见 [完整包测量](../docs/rust-feasibility/assessment.md)。
