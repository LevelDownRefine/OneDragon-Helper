# tools/ 副本同步脚本

`config/dungeon_list.yml` 各游戏副本列表的维护方式总览。**除原神外均可自动更新**（GitHub Actions 每周六凌晨自动检测 + 开 PR），原神因 display 需人工套装配对走手动流程。本目录是开发/CI 工具（区别于 `scripts/`——脚本链运行器执行的实际脚本）。

## 各游戏副本更新方式

| 游戏 | yml key | 副本数据源 | 更新方式 | 人工环节 |
|---|---|---|---|---|
| 终末地 | `ok-ef` | ok-end-field `assets/data/world_map.json` 的 `stages_dict` | `sync_okef_dungeons.py` + Action 自动 | 无（display=value=关卡名） |
| 鸣潮 | `ok-ww` | ok-wuthering-waves `ForgeryTask.py`/`TacetTask.py` 的 `self.structure`（sum=总数） | `sync_okww_dungeons.py` + Action 自动补数字 | 新数字 display 改友好名（梦州-迅刀 等） |
| 异环 | `ok-nte` | ok-nte `AnomalyTask.py` 的 `_ID_RANGE` | `sync_oknte_dungeons.py` + Action 自动补数字 | 新数字 display 改友好名（光暗/鸟 等） |
| 原神 | `BetterGI` | better-genshin-impact `AutoTrackPath/Assets/tp.json` | 手动（skill: `sync-bgi-dungeons`） | 分类 + display 套装配对 |
| 明日方舟 | `MAA` | 固定 | 无需更新 | — |
| 崩铁 | `March7th-Assistant` | 固定 | 无需更新 | — |
| 绝区零 | `OneDragon-Launcher` | 固定 | 无需更新 | — |

## 通用约定

- **数据源可靠性**：以脚本仓库自身代码/数据为准（同源权威）；`bettergi-scripts-list` 的 JS 脚本层滞后于主程序，不可作来源；AI 生成的 JSON 不可信。
- **退出码**：所有 sync 脚本 `0` = 无差异（或已应用）、`1` = 有差异未应用（供 CI 判断）、`2` = 抓取/解析失败（网络错误或上游结构变化，CI 跳过本次不开 PR）。
- **`--apply`**：自动补齐新增条目（终末地整块补齐；鸣潮/异环补数字占位条目 `display=数字`）；**移除仅报告不删除**（防上游短暂回退丢配置）。
- **yml 格式**：dungeon_list.yml 由 yaml 统一管理（无注释、`sort_keys=False` 幂等），脚本重写后 diff 只含真实增量。
- **Action 产物**：自动更新开 PR，占位 display 需人工改友好名后合并；终末地无占位可直合。

## 脚本用法

```bash
python tools/sync_okef_dungeons.py            # 检测终末地差异
python tools/sync_okww_dungeons.py --apply    # 检测鸣潮并自动补齐数字
python tools/sync_oknte_dungeons.py           # 检测异环差异
```

原神手动流程见 `.workbuddy/skills/sync-bgi-dungeons/SKILL.md`。
