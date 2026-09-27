# Rust GUI / Python CLI 迁移

保留助手的 Python 配置适配与业务逻辑，通过无 Qt CLI 为后续 Rust 界面提供接口。
当前可在现有 GUI 中运行 `python -m src.launcher --cli-backend`，验证任务卡读写。

- [GUI / CLI 边界设计](gui-cli-boundary.md)：现有调用、迁移范围及后续接口。
- [无 Qt CLI](headless-cli.md)：运行方式、协议、任务卡字段与错误处理。
