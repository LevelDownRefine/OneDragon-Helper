# tools/ 副本同步脚本

config/dungeon_list.yml 各游戏副本列表维护总览。除原神外均可自动更新，GitHub Actions 每周六检测并开 PR；原神因 display 需人工套装配对走手动流程。本目录是开发/CI 工具，区别于 scripts/ 的实际运行脚本。

## 各游戏副本更新方式

| 游戏 | yml key | 副本数据源 | 更新方式 | 人工环节 |
|---|---|---|---|---|
| 终末地 | ok-ef | ok-end-field assets/data/world_map.json 的 stages_dict | sync_okef_dungeons.py + Action 自动 | 无 |
| 鸣潮 | ok-ww | ok-wuthering-waves ForgeryTask.py/TacetTask.py 的 self.structure | sync_okww_dungeons.py + Action 自动补数字 | 新数字改友好名 |
| 异环 | ok-nte | ok-nte AnomalyTask.py 的 _ID_RANGE | sync_oknte_dungeons.py + Action 自动补数字 | 新数字改友好名 |
| 原神 | BetterGI | better-genshin-impact AutoTrackPath/Assets/tp.json | 手动 skill: sync-bgi-dungeons | 分类 + display 套装配对 |
| 明日方舟 | MAA | 固定 | 无需更新 | — |
| 崩铁 | March7th-Assistant | 固定 | 无需更新 | — |
| 绝区零 | OneDragon-Launcher | 固定 | 无需更新 | — |

## 通用约定

- 数据源可靠性：以脚本仓库自身代码/数据为准；bettergi-scripts-list 的 JS 层滞后不可作来源；AI 生成的 JSON 不可信。
- 退出码：0 = 无差异，1 = 有差异未应用供 CI 判断，2 = 抓取/解析失败 CI 跳过。
- --apply：自动补齐新增条目；移除仅报告不删除，防上游短暂回退丢配置。
- yml 格式：由 yaml 统一管理，无注释、sort_keys=False 幂等，diff 只含真实增量。
- Action 产物：自动更新开 PR，占位 display 需人工改友好名后合并；终末地无占位可直合。

## 脚本用法

```bash
python tools/sync_okef_dungeons.py
python tools/sync_okww_dungeons.py --apply
python tools/sync_oknte_dungeons.py
```

原神手动流程见 .workbuddy/skills/sync-bgi-dungeons/SKILL.md。
