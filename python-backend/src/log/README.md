# 日志位置与分析规则

各脚本固定的日志位置与分析关键词统一放在 `config/log_analysis.yml`。
`config/config.yml` 只保存安装路径、无日志超时及重试次数等用户设置。

```yaml
parsers:
  ok-ef:
    log_path: data/apps/ok-ef/working/logs/ok-script.log
    log_analysis_path: '%TEMP%/ok-ef/日常任务/日常任务_*.txt'
  MaaEnd:
    log_path: debug/maafw.log
```

- `log_path`：实时日志文件，也是 GUI「打开日志」的目录来源。
- `log_analysis_path`：仅分析文件不同于实时日志时填写；省略时沿用 `log_path`。
  终末地的任务汇总仍用于成败分析，不能用它检测运行时日志活动。
- 相对路径基于脚本所在目录；绝对路径直接使用；`%TEMP%/` 基于系统临时目录。
- 仅文件名允许 `*`、`?` 等通配符，不允许目录通配或递归扫描。
- 未声明或空字符串表示不使用文件日志，不猜测其它文件。
- 声明路径不要求已实现成败解析器；MAA、MaaEnd 同样可以监测文件和打开日志目录。

生成运行链时，service 按脚本标识读取声明，将实时日志解析为绝对路径后写入链的
`log_path`。runner 只消费这份链，不依赖助手的 YAML 结构，也不会拿分析报告判断活动。
主配置和新增脚本不再保存日志路径；残留旧字段不覆盖声明。

MAA 与 [AUTO-MAS 的 MAA 适配](https://github.com/AUTO-MAS-Project/AUTO-MAS/blob/a38bfc26229d788b643f74fb420a6ddf5d81df56/app/task/MAA/AutoProxy.py#L335)
使用同一个 `debug/gui.log`。该文件在正常作战期间也可能长时间不更新；
无日志阈值由用户设置，不自动放宽。正常等待超过阈值同样触发，
该检测不能区分正常静默与卡死。

MaaEnd 使用 MaaFramework 的实时执行日志 `debug/maafw.log`；
文件轮转时仍监测同一活动文件。
位置也见 [MaaFramework 文档](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/1.1-%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.md)。

阻塞外部脚本开启无日志超时后，runner 每秒检查文件大小、修改时间和文件标识；
控制台输出或文件变化任一有活动就刷新计时。每次启动前建立基线，旧日志不变不算活动；
支持运行后创建、改写、截断和轮转，不读取日志内容、不增加线程或依赖。
空路径只检查控制台输出。`no_log_timeout_seconds: 0` 关闭无日志检测；
`no_log_max_retries: 0` 只关闭脚本、不重试。
