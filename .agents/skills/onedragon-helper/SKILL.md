---
name: onedragon-helper
description: 执行或检查 OneDragon-Helper 子脚本，定位目录、日志和仓库，分析异常与根因；经用户同意修复子脚本 bug 并提 PR。
---

# OneDragon-Helper 执行与检查

运行任务按“执行”，分析已有记录按“检查”。检查工具复用助手后端函数；启动脚本、修改任务及配置仍通过安装包 CLI，参数见 [CLI 参考](references/cli.md)。

## 准备源码与工具

每次任务开始先在 Skill 目录运行：

```powershell
uv run scripts/odh.py setup
```

`setup` 从 [助手仓库](https://github.com/LevelDownRefine/OneDragon-Helper) 获取并快进更新 GitHub 默认分支的最新源码，默认放在操作系统缓存目录，不按 EXE 版本锁定。自动获取需要 Git；工具需要 Python 3.11+ 和 `ruamel.yaml`，`uv run` 可准备 Python 运行环境及依赖。

离线或使用已有源码时，跳过 `setup`，给后续命令加 `--source '已有源码根目录'`，不联网更新。以下检查命令的 `--install` 指向完整 EXE 安装目录：

```powershell
uv run scripts/odh.py --install 'D:\OneDragon-Helper' list
uv run scripts/odh.py --install 'D:\OneDragon-Helper' inspect --script ok-ww
uv run scripts/odh.py --install 'D:\OneDragon-Helper' logs --script ok-ww --kind analysis --limit 5
uv run scripts/odh.py --install 'D:\OneDragon-Helper' analyze --script ok-ww
uv run scripts/odh.py read-log --path '查询返回的日志路径' --find ERROR --context 5
```

| 命令 | 用途 |
| --- | --- |
| `list` | 查询脚本标识、展示名和启动路径 |
| `inspect` | 定位目录、实际仓库、实时与分析日志及规则；`--script` 可重复 |
| `logs` | 列出日志文件、大小和时间；`--kind realtime/analysis/helper/runner` 选类别，`--limit` 限数量 |
| `analyze` | 调用已有解析器取得完成状态提示；`--script` 可重复，未支持或禁用分析时为未知 |
| `read-log` | 读取带行号原文；`--start-line/--lines` 选段，`--find/--context/--max-matches` 查字面文本及上下文，`--encoding` 指定编码 |

工具输出 JSON。留意源码 commit、安装的 `helper_version` 和读取错误：最新源码可能与旧 EXE 存在差异，按实际结果定位兼容性问题，不自动更新 EXE。子脚本版本需另外核对；仓库来源未知时查其本地 Git remote 或 README，不把助手仓库当作子脚本仓库。

## 执行

1. **确定范围。** 用 `list` 或 `app.snapshot` 取得脚本标识，`run.view` 检查运行条件、已有选项及重跑设置。`--enable` 传明确的非空清单；省略或空字符串会选全部，执行顺序取配置列表顺序。
2. **按需改任务。** 用 `script.view` / `script.edit_view` 查询当前值与选项，通过 CLI 保存并回读。未提供的能力查子脚本原生入口。仅本次生效的修改要记录原值和恢复方法；普通保存及 `run.prepare` 都会持久化，后者只返回运行目标，不启动。
3. **运行并等待。** 记录开始时间，向 CLI EXE 传入 `legacy -- --schedule-run now --enable "脚本标识A,脚本标识B"`，等待执行、内置重跑和后处理结束。内置重跑启用时只补跑一轮，限所选且有解析器、日常未完成的脚本（含无日志）；Runner 无日志超时重启另行计数。
4. **检查后收尾。** 按下方检查流程核对本轮日志，正常退出也要检查。只补跑仍失败的脚本，并计入已有重跑；结果不明先补证据，同一原因再次失败且无新办法时停止。恢复临时修改并回读，报告各脚本结果、异常、任务变更和补跑情况。

## 检查

1. **定位记录。** 用 `inspect` 确定目录、日志规则及仓库，`logs` 找相关文件，核对子脚本版本和检查时段。助手运行记录通常在安装目录的 `logs/onedragon_helper.plan-YYYY-MM-DD.log`。
   日志含 `%TEMP%` 时，核对助手运行账户的实际临时目录；沙箱可能改写它，必要时为工具进程设置正确的 `TEMP` / `TMP` 后重查。
2. **核实结果与异常。** `analyze` 提供线索，再用 `read-log` 对照启动、执行、重试和结束原文。区分首轮与重跑，检查已恢复的报错、反复重试、跳过任务及异常耗时；完成状态和异常分别报告，证据注明文件、时间或行号。缺失证据保留未知。
3. **定位根因。** 结合日志、实际配置和对应版本的子脚本源码，区分配置、环境、助手适配与子脚本问题。说明已证实原因、待验证假设及仍缺的证据。
4. **修复与 PR。** 需要修复子脚本时，先说明仓库、修改位置、方案、验证方式和 PR 目标，取得修复及提 PR 的同意；已有授权不重复询问。按子脚本开发说明修改并验证，交付 PR 链接，并说明本机版本是否已应用修复。

解析器按凌晨 **04:00** 划分运行日，可能读入同日旧日志，`analyze` 结果不代表本轮最终结果。`--schedule-run` 退出 0 不等于任务成功；`script.view` 查询配置，`job.poll` 仅跟踪 CLI 后台维护任务，不跟踪游戏运行。

## 其他操作

具体参数、完整保存字段及副作用见 [CLI 参考](references/cli.md)，不要从方法名猜参数。

| 任务 | CLI 入口 |
| --- | --- |
| 日常副本、开关、周常及起始日 | `script.view`、`daily.*`、`weekly.*` |
| 原生任务开关、业务选项、路径和名称 | `script.edit_view/edit_save`；`task_options` 只提交改动项 |
| 脚本增删排序 | `script.add/remove/reorder` |
| 运行选项、每日计划 | `run.view`、`plan.view/save`；计划问题还需核对系统任务实际状态 |
| 配置备份恢复、助手更新 | `backup.start/restore.start`、`update.*`，在同一 `serve` 会话用 `job.poll` 等待结果 |
