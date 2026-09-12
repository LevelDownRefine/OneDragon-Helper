# tools/ 副本同步脚本

config/daily_task_list.yml 各游戏副本列表维护总览。鸣潮/异环经 GitHub Actions 每周六检测并开 PR；原神、终末地经 options.source 运行期读取脚本自身资源。本目录是开发/CI 工具，区别于 scripts/ 的实际运行脚本。

## 各游戏副本更新方式

| 游戏 | yml key | 副本数据源 | 更新方式 | 人工环节 |
|---|---|---|---|---|
| 终末地 | ok-ef | ok-ef 自身 world_map.json | options.source 运行期读取，无需 Action | 无 |
| 鸣潮 | ok-ww | ok-wuthering-waves ForgeryTask.py/TacetTask.py 的 self.structure | sync_okww_tasks.py + Action 自动重排（最前插入，已有别名后移） | 最前新增占位改友好名 |
| 异环 | ok-nte | ok-nte AnomalyTask.py 的 _ID_RANGE | sync_oknte_tasks.py + Action 自动补数字 | 新数字改友好名 |
| 原神 | BetterGI | better-genshin-impact AutoTrackPath/Assets/tp.json | options.source 运行期读取，无需 Action | 无 |
| 明日方舟 | MAA | 固定 | 无需更新 | — |
| 崩铁 | March7th-Launcher | 固定 | 无需更新 | — |
| 绝区零 | OneDragon-Launcher | 固定 | 无需更新 | — |

## 通用约定

- 数据源可靠性：以脚本仓库自身代码/数据为准；bettergi-scripts-list 的 JS 层滞后不可作来源；AI 生成的 JSON 不可信。
- 退出码：0 = 无差异，1 = 有差异未应用供 CI 判断，2 = 抓取/解析失败 CI 跳过。
- --apply：鸣潮按最前插入模型重排——新增 delta 个时已有 physical_name 整体 +delta、最前补占位；移除仅报告不删除（无法安全重排），防上游短暂回退丢配置。
- yml 格式：由 yaml 统一管理，无注释、sort_keys=False 幂等，diff 只含真实增量。
- 选项格式：任务和选项统一用 display_name / physical_name；子选项放 options.values，读写字段放 options.key。
- Action 产物：自动更新开 PR，最前新增的占位 display_name 需人工改友好名、已有别名已被自动后移，核对后合并。

## 脚本用法

```bash
python tools/sync_okww_tasks.py --apply
python tools/sync_oknte_tasks.py
```

周常声明单独在 config/weekly_task_list.yml，不由上述两个同步脚本更新。
