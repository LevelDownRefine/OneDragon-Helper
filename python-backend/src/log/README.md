# 日志与分析

脚本日志位置和分析关键词统一声明于 `config/log_analysis.yml`，用户配置只保存安装路径、超时和重试次数。

```yaml
parsers:
  ok-ef:
    log_path: data/apps/ok-ef/working/logs/ok-script.log
    log_analysis_path: '%TEMP%/ok-ef/日常任务/日常任务_*.txt'
```

| 字段 | 用途 |
| --- | --- |
| `log_path` | 实时活动检测及 GUI「打开日志」 |
| `log_analysis_path` | 成败分析；省略时沿用实时日志 |

相对路径基于脚本目录，支持绝对路径与 `%TEMP%/`。通配符只允许出现在文件名，不扫描通配目录；未声明或空路径表示不使用文件日志。日志定位不要求已实现成败解析器。

service 生成运行链时将实时路径注入 runner，旧用户配置中的日志路径不覆盖声明。分析报告不能代替实时活动检测。

阻塞外部脚本启用检测后，控制台输出或文件变化都会刷新计时；启动前的旧日志不算活动，支持文件创建、截断及轮转。空路径只监测控制台。`no_log_timeout_seconds: 0` 关闭检测，`no_log_max_retries: 0` 关闭重试。

MAA 使用 `debug/gui.log`，正常作战也可能长时间不写日志；阈值由用户设置，检测无法区分静默等待与卡死。MaaEnd 使用 `debug/maafw.log`。

助手按日写入安装根目录的 `logs/`：GUI 为 `onedragon_helper-日期.log`，计划/运行为 `onedragon_helper.plan-日期.log`，保留 14 天；runner 使用独立的 `.log/`。验证入口见 [测试指南](../../../docs/TESTING.md)。
