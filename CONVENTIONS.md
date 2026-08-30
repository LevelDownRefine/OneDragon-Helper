# CONVENTIONS.md — 编码约定全文

> 本文件是 AGENTS.md「铁律」的完整版与澄清落点。AGENTS.md 只列要点，细节与边界以本文件为准。
> 约定为「强偏好，违反即打回」。

## 1. 严格 `assert` 表达「不该发生」

`assert` 只用于表达编程错误：前置/不变量被破坏、不可达分支。可恢复情况——外部输入、文件缺失、用户取消——用 `return False` / 跳过 / 抛业务异常，不要用 assert 当校验。

```python
assert "script_path" in script          # 不该缺失 → 用 assert
resolved = resolve_script_path(script["script_path"])
if not os.path.exists(resolved):
    return f"脚本不存在 {script['script_path']}"   # 可恢复 → 返回原因
```

## 2. 字典访问不用 `.get()`

先 `assert key in dict` 再直接 `dict[key]`。`.get()` 会掩盖「字段不该缺失」的错误，让 bug 静默变成 `None`。

```python
assert "script_type" in script
script_type = script["script_type"]
```

> 注：仅在「字段确实可选、缺失即走默认」的少数场景可用 `.get()`，但需显式给出默认值并注释原因；不要无默认值裸 `.get()`。

## 3. 不静默吞异常，与 #12「是否用 try」正交

`except` 分支不得 `pass`、不得裸吞；被捕获的异常必须显式处理——记录 / 回退 / 重抛——不得悄无声息消失。

- 「是否用 `logger` 记录」与「是否用 try 捕获」是**两个独立问题**：try 用于规避可预见的错误，logging 用于把已处理、含被捕获的异常留痕。
- 若捕获后选择记录，记**异常类型**，至少 `type(e).__name__`，必要时 `exc_info=True`，便于事后定位，不要只打一句泛化文案。

```python
try:
    proc = subprocess.run(command, timeout=30)
except subprocess.TimeoutExpired as e:
    proc = getattr(e, "subprocess", None)
    if proc is not None:
        proc.kill()
    logger.error("命令超时未响应：%s", command)
    return False
```

> 边界：headless / 无桌面等环境下 GUI（Qt 等）初始化失败属可预见，须包 try 并记诊断，不能 `except Exception: pass` 让失败静默成「取消」且无日志（如 ``utils_shutdown._confirm_shutdown`` 按取消处理并记 error）。

## 4. 命名显式明确

`self.display_name` 优于 `self.name`；模块/函数名表达意图。不留兼容别名，删旧名并改调用点。

## 5. 多实体共享/注册优先 OOP 类层级

同类多实体，如各游戏脚本的 config 适配、各副本解析，用 `class` 层级 + 注册表，而非 `function + dict` 散查。结构集中、扩展点清晰。

## 6. 重构只在有明确收益时做

反对 scope-creep。1 处调用点不抽函数；没有复用诉求不提前抽象。重构须带来可读/可测/去重等实质收益，否则保持原样。

## 7. 禁止绕过依赖/CI 的 workaround

不允许 `skipUnless`、按 `os.name` 分支跳过、注释掉校验等绕过手段。CI 挂的真因要修，不绕过。

## 8. 日志用 `logging` 模块

`logger = logging.getLogger(__name__)`；入口调 `setup_logging()`，控制台加文件轮转。禁止裸 `print`。

- runner 子模块有独立日志系统 `.log/`，遵循其自身约定。

## 9. GUI 持久化边界

`gui_state.json` 只存 `dungeon` / `sequence`；`enabled` 纯内存态，重启恢复全开，不持久化。

## 10. 不随意修改 `.bak` / 备份文件

备份文件如 `.bak` 默认只读参考。需改动时先征得用户同意，不在无人确认下动备份。

## 11. 必须补测试并跑全套

新增/修改功能后必须补测试。动了共享接口 / 多模块 / 做了重构的**大改动**，必须用与 CI 一致的命令跑**全量**，不能只跑改动相关文件：

```bash
PYTHONPATH=src python -m unittest discover -s tests -p "test*.py"
```

- `PYTHONPATH=src` 不可省：否则 `test_bgi` / `test_utils` 顶层 `import` 会误报 import 错。
- `ruff check src tests` 一并跑，含 `src/runner/`。

## 12. 克制使用 try-except

仅在确有必要时才捕获，使用前须有明确理由；`except` 应尽可能显式指定异常类型，避免 `except Exception`，优先用 `if` 判断规避可预见的错误，如先 `os.path.exists` 再打开。

- 被捕获异常的处理方式，是否 `logger.warning`，与「是否用 try」正交，见 #3。
- 宽泛捕获带 `noqa` + 明确理由的，不在本项目约束内的外部模块可酌情放宽，如 runner、cli.py、icons.py。

## 13. Commit 规范且简短

Conventional Commits 前缀：`feat` / `fix` / `refactor` / `chore` / `docs` / `test` / `style`，一句话主题，≤50 字符。如 `refactor: 抽取 service 层`。

- submodule 与 主仓分开提交；先推 submodule 再推主仓，避免主仓指针悬空。

## 14. 备注/日志规范且简短

工作日志、代码注释、`[startup]` 等备注一律只记要点：改动、原因、效果，不写过程叙述、流水账与复述性说明。函数文档对齐所在文件既有风格：主仓 Google 风格、runner reST `:param:`/`:return:`，新增函数须与所在文件一致，且保持简洁。
