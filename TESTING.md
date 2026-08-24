# TESTING.md — 测试与开发工作流

铁律：改代码前先激活 venv，改完必须跑测试 + ruff。

## 0. 前置：激活环境

```bash
source .venv/Scripts/activate    # bash / git bash
call env.bat                     # cmd，同时设置代理 127.0.0.1:7890
```

未激活环境是最常见的本地能跑、CI 挂或 ImportError 根因。

## 1. 跑测试

```bash
cd <root> && export PYTHONPATH=src && python -m unittest discover -s tests -p "test*.py"
```

python -m 把根目录加入 sys.path，PYTHONPATH=src 让 import launcher 可用；两种 import 风格并存，必须在根目录且带 PYTHONPATH=src 跑。测试文件与源码一一对应；GUI 测试开头设 QT_QPA_PLATFORM=offscreen 无头跑 PySide6。文件 I/O 一律 mock，不依赖真实 config 或游戏脚本路径。新增/修改功能后必须补测试并跑全套再交付。

## 2. 风格检查 ruff

```bash
ruff format .
```

含 src/runner/，也是我们的代码。

## 3. 加依赖

改 pyproject.toml → uv sync 同步 uv.lock。

## 4. 调试

先看日志再下结论：主程序日志在 logs/onedragon_helper.log，每日 00:00 轮转，保留 14 天。运行器子进程有独立日志系统 .log/。子脚本日志目录见 src/log/monitor 各 Parser 的 _get_log_dir。日志汇总：python -m src.log。
