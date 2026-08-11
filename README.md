# OneDragon-Helper

本项目是多游戏自动化脚本调度器，支持多个游戏的脚本调度。
![ds](assets/ds.jpg)
Agent兴起，可以借助Agent快速自定义脚本级别工具。

## 功能

- 更改各脚本配置
- 非阻塞运行脚本
- 日志解析与重新运行
- PySide6 图形界面：选脚本 / 副本 / 超时 → 生成脚本链 → 运行（界面样式统一由 `src/gui/theme.py` 主题层管理）

## install

`uv sync`

## activate on cmd

`.venv\Scripts\activate.bat`

## run

`python -m src.launcher`
