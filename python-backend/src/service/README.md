# 服务层

`AppService` 是后端统一业务入口，由 CLI 装配和调用；两套 GUI 只消费 CLI 协议。它装配平级服务并薄委托，无 Qt 依赖。配置适配归 set_config，执行归 runner，展示状态归前端。

## 模块职责

| 模块 | 职责 |
| --- | --- |
| `app_service.py` | 组合根与公开接口 |
| `script_service.py`、`task_service.py` | 脚本增删改排序、表单校验、任务查询 |
| `chain_service.py`、`chain_gen.py` | 链生成、校验和 runner 命令 |
| `schedule.py`、`run_actions.py` | 运行选项、调度、前后动作与失败重跑 |
| `daily_plan.py` | 每日计划、Windows 任务注册与状态回读 |
| `backup_service.py` | 配置 ZIP 备份与恢复 |
| `../link.py`、`../utils/utils_wallpaper.py` | 资源/启动目标、壁纸映射与缓存 |
| `../update.py`、`../utils/utils_job.py` | 更新适配与会话、后台任务执行 |

## 查询与保存

任务卡查询保留适配器原值：日常 `name/task/sequence/enabled/options`，周常 `name/task/options/start_day`。整数、布尔、`0` 和 `None` 不混用。查询可能触发既有模板初始化或格式迁移，不承诺完全无写盘副作用。

日常选择、启停和周常选择薄委托原接口；写后刷新由调用方另行请求。周常起始日先保存助手侧意图，再同步原生配置；后一步失败不撤销意图。落点见 [配置适配](../config/set_config.md)。

脚本标识：EXE 使用不含扩展名的文件名，其他脚本使用展示名。保存前校验完整表单；依次保存助手配置、每周标识及超时，按需清除适配器缓存，再保存附带选项和原生开关。后续失败可能部分落盘，调用方须重读列表及表单，不自动重试。

[附带选项](../config/task/task_options.md) 只提交变化的字段；保存前重读文件并校验。选项先于开关写入，防止共享文件被旧内容覆盖。取消编辑不调用保存。

## 运行与计划

`AppService.prepare_run` 校验并保存确认后的选项，反读不含授权码的 `RunOptions`；`saved_run` 校验名单和已存选项，不保存或运行。CLI 适配器将业务结果转换为 `run.prepare` / `run.saved` 的独立运行命令及 stdin 数据，前端负责进程启动。运行进程持锁，依次完成配置准备、运行链、日志分析、重跑与汇总；凭据不进入命令行或查询响应。CLI 字段和进程交接见 [协议](../../../docs/rust-feasibility/headless-cli.md)。

手动勾选仅由前端持有。每日计划默认关闭，默认时间 04:10；启用后对所有脚本生效，使用 `schedule.yml` 中独立的 `daily_run` 选项。

Windows 任务按当前用户和安装目录标识，需管理员权限注册及用户登录后运行，不负责唤醒或补跑。配置表示意图，系统任务状态表示实际结果。保存时先注册任务再写配置；写盘失败恢复旧 XML，原先未注册则删除新任务。移动安装目录前先停用旧计划。

## 备份恢复

备份范围来自 [脚本资源声明](../config/script_resources.md)，ZIP 按 `scripts/脚本名/相对路径` 收集。恢复到当前配置的脚本目录；未配置脚本跳过，已有游戏路径（包括空值）保留，缺失时不导入备份中的旧路径。

覆盖前备份目标文件，逐文件原子替换；不承诺整批事务回滚。失败结果保留完成数量和恢复前 ZIP，供用户核对。归档安全检查与路径校验归后端。

## 手动更新

更新内核独立维护于 `updater/`；`src/update.py` 负责助手适配、`UpdateSession` 和独立更新器入口，AppService 只委托。

- 打开更新窗只读本地信息；显式检查稳定版后，下载同一会话中的版本。
- 按安装清单区分 Qt/Rust 包；源码不支持原位安装。
- 按清单与哈希复用本地文件、下载差异；服务器不支持范围请求时回退整包续传。安装所有权记录在 `.update/`。
- 临时更新器就绪后等待 GUI/CLI 退出并取得独占租约；其他窗口或 Runner 占用时拒绝安装，不强杀它们。
- 安装后带 `--after-update` 重启，避免自动运行。失败诊断与恢复入口由更新结果提供；使用提示的 `--recover` 命令恢复。

后台任务的互斥、取消、EOF 和交接规则集中在 [CLI 协议](../../../docs/rust-feasibility/headless-cli.md)。测试见 [测试指南](../../../docs/TESTING.md)。
