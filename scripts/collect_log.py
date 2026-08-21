"""
各游戏脚本运行日志的解析与汇总。

每款游戏对应一个 `*LogParser` 子类，从其日志判定运行结果（成功 / 失败 / 无日志）；
`parse_log` 按 script_name 找到对应 Parser 并解析单个脚本；`parse_logs` 先收集各脚本解析
结果，再分别由 `_build_summary_report` 生成汇总表格、`_prepare_action_lists` 准备需处理脚本列表
（重跑 / 通知）。失败重跑由同目录 `rerun.py`、报错邮件由同目录 `notify_mail.py` 负责，二者均调用
本文件 `parse_logs`（后者复用其返回的汇总表格做整表通知）。

可独立运行：python scripts/collect_log.py。除复用核心代码 `get_script_name` 外，不依赖
项目内其余模块；自行推导根目录并直接 `yaml.safe_load` 读取 `config.yml`。
"""

import logging
import os
import re
import sys
import tempfile
import unicodedata
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import yaml

# 项目主流程已允许本脚本复用核心代码（未来将迁入主流程），
# 因此直接复用脚本唯一标识 get_script_name，避免手抄其逻辑。
# exe 脚本标识=进程名（script_path basename 去后缀，空格→-），python 脚本=display_name。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from src.config.subscript import get_script_name  # noqa: E402

logger = logging.getLogger(__name__)


def log_info(msg, *args, do_log: bool = True) -> None:
    """统一日志打印入口；do_log=False 时静默。"""
    if do_log:
        logger.info(msg, *args)


def _get_root_dir() -> str:
    """推导项目根目录（向上 2 层：scripts/collect_log.py → 项目根）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cell_width(text: str) -> int:
    """计算字符串显示宽度（CJK/全角字符记 2，其余记 1），用于表格对齐。"""
    width = 0
    for ch in str(text):
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _pad_row(cells: list[str], widths: list[int]) -> str:
    """按给定列宽拼接一行表格（右补空格，CJK 宽度感知）。cells 与 widths 等长。"""
    parts = []
    for cell, width in zip(cells, widths, strict=True):
        text = "" if cell is None else str(cell)
        parts.append(text + " " * max(0, width - _cell_width(text)))
    return "".join(parts)


def _resolve_daily(daily_raw: bool | None, status: str) -> bool:
    """推导每日是否做完：日志有明确信号（True/False）时直接用；

    日志未提及（None）时按整体运行状态推断——每日脚本整体跑成即视为当日做完，
    失败 / 无日志即未做。避免「未知」这类模棱两可的呈现。
    """
    if daily_raw is not None:
        return daily_raw
    return status == ScriptLogStatus.SUCCESS


def _resolve_exited(exited_raw: bool | None, status: str) -> bool:
    """推导是否正常退出：日志有明确信号（True/False）时直接用；

    无日志（None）时按整体运行状态推断——整体跑成即视为已退出，
    失败 / 无日志即未正常退出。避免「未知」这类模棱两可的呈现。
    """
    if exited_raw is not None:
        return exited_raw
    return status == ScriptLogStatus.SUCCESS



_LOG_TAIL_LINES = 200

_LOG_CONFIGURED = False


def _setup_logging() -> None:
    """配置日志：控制台 + 按天轮转文件 logs/collect_log.log（保留 14 天）；幂等。"""
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    log_dir = Path(_get_root_dir()) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        str(log_dir / "collect_log.log"),
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    _LOG_CONFIGURED = True


class ScriptLogStatus:
    SUCCESS = "Success"
    FAILED = "Failed"
    NO_LOG = "NoLog"
    # 显示层状态：脚本正常完成（SUCCESS）但日志含报错，由 parse_logs 推导，
    # 解析器不直接返回。仅用于汇总表状态列，不影响 rerun/notify 决策。
    WARN = "Warn"


# 状态中文映射；覆盖 parse() 与显示层全部真实状态，未知状态属不可能（统一用 assert 兜底）。
status_cn = {
    ScriptLogStatus.SUCCESS: "成功",
    ScriptLogStatus.FAILED: "失败",
    ScriptLogStatus.NO_LOG: "无日志",
    ScriptLogStatus.WARN: "有报错",
}


class BaseLogParser:
    # 脚本唯一标识（与全链路一致，见 src.config.subscript.get_script_name）：
    # exe 脚本=进程名（script_path basename 去后缀，空格→-），python 脚本=display_name。
    # parse_log 与 supported 推导都按它匹配，不再依赖易变的 display_name。
    script_name: str = ""
    # 判定某行是否为报错的子串标记。
    error_markers: tuple[str, ...] = ("ERROR",)
    # 命中 error_markers 但实为良性噪声（启动瞬断 / 战斗复检 / 关机收尾等）的子串，
    # 含这些子串的行不计入报错。
    error_noise: tuple[str, ...] = ()

    def get_log_path(self, script_path: str) -> Path | None:
        log_dir = self._get_log_dir(script_path)
        if not log_dir or not log_dir.exists():
            return None

        log_files = sorted(log_dir.glob(self._get_log_pattern()), reverse=True)
        for log_file in log_files:
            if self._is_valid_log(log_file):
                return log_file
        return None

    def _get_log_dir(self, script_path: str) -> Path:
        raise NotImplementedError

    def _get_log_pattern(self) -> str:
        raise NotImplementedError

    def parse_content(self, content: str) -> str:
        raise NotImplementedError

    def _read_file(self, path: Path) -> str:
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(path, encoding="gbk") as f:
                return f.read()
        except Exception:
            return ""

    def _is_valid_log(self, log_path: Path) -> bool:
        now = datetime.now()
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime)

        if now.hour >= 4:
            return mtime.date() == now.date()

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if mtime >= today_start:
            return True

        yesterday_4am = (now - timedelta(days=1)).replace(
            hour=4, minute=0, second=0, microsecond=0
        )
        return mtime >= yesterday_4am

    # ---- 四类补充信息提取（各子类按需覆写） ----
    # 体力提取正则：第一个捕获组为剩余体力数字；不设置（为空）表示日志不含体力。
    stamina_pattern: str = ""

    def parse_stamina(self, content: str) -> str | None:
        """剩余体力（各游戏称谓不同）。子类以 stamina_pattern 提供提取正则，
        取最后一个匹配的第一个数字组；不设置 stamina_pattern 或提取不到返回 None。"""
        if not self.stamina_pattern:
            return None
        matches = re.findall(self.stamina_pattern, content)
        if not matches:
            return None
        last = matches[-1]
        # 单组正则返回 str，多组正则返回 tuple；统一取首个数字组。
        return last[0] if isinstance(last, tuple) else last

    def parse_daily(self, content: str) -> bool | None:
        """是否做完每日：完成=True，未完成/部分失败=False，日志未提及=None（由表格层按整体状态推断）。"""
        return None

    def parse_exit(self, content: str) -> bool | None:
        """是否正常退出：是=True，异常退出=False，无法判定=None。"""
        return None

    def parse_extra(self, content: str) -> str | None:
        """额外信息（游戏特定）。默认无；子类（如原神浓缩树脂）按需覆写。"""
        return None

    def _error_body(self, content: str) -> str:
        """报错扫描的作用区间。默认整段；子类（如崩铁）可截断到「游戏终止」之前。"""
        return content

    def collect_error_lines(self, content: str, limit: int = 10) -> list[str]:
        """收集去重后的报错行（已过滤 error_noise）。空列表表示无报错。"""
        body = self._error_body(content)
        errors: list[str] = []
        for line in body.splitlines():
            if not any(m in line for m in self.error_markers):
                continue
            if any(n in line for n in self.error_noise):
                continue
            text = line.strip()
            if text and text not in errors:
                errors.append(text)
            if len(errors) >= limit:
                break
        return errors

    def parse(self, script_path: str = "") -> dict:
        log_path = self.get_log_path(script_path)
        if not log_path or not log_path.exists():
            return {
                "status": ScriptLogStatus.NO_LOG,
                "log_path": str(log_path) if log_path else None,
            }

        content = self._read_file(log_path)
        status = self.parse_content(content)
        # daily_done 在此层定稿：parse_daily 是每类自己的方法（产出日志原话信号），
        # 缺信号时按本类 status 推断（成功=做了每日），保证出厂即为确定 bool。
        daily_done = _resolve_daily(self.parse_daily(content), status)
        return {
            "status": status,
            "log_path": str(log_path),
            "log_content": content[-2000:] if len(content) > 2000 else content,
            # 四类补充信息，向后兼容：旧消费者只用 status/log_path/log_content。
            "stamina": self.parse_stamina(content),
            "daily_done": daily_done,
            "exited": _resolve_exited(self.parse_exit(content), status),
            "errors": self.collect_error_lines(content),
            "extra": self.parse_extra(content),
        }


class OkWwLogParser(BaseLogParser):
    script_name = "ok-ww"
    # 仅取剩余体力数字（current_stamina），不记录总体力 / 储备。
    stamina_pattern = r"info_set current_stamina (\d+)"
    # 启动瞬断 / 战斗复检 / 关机收尾产生的 ERROR 属良性噪声，不计入报错。
    error_markers = ("ERROR",)
    error_noise = (
        "target_enemy failed",  # 战斗复检，可自行恢复
        "combat check not in combat",  # 同上
        "Failed to terminate process",  # 关机收尾
        "Game window is not connected",  # 启动瞬断
        "waiting for game to start error",  # 启动瞬断
        "capture_by_bitblt invalid params",  # 启动瞬断（hwnd=0）
    )

    def _get_log_dir(self, script_path: str) -> Path:
        ok_ww_dir = Path(script_path).parent
        return ok_ww_dir / "data" / "apps" / "ok-ww" / "working" / "logs"

    def _get_log_pattern(self) -> str:
        return "ok-script.log"

    def parse_content(self, content: str) -> str:
        if "Successfully Executed Task" in content or "Task completed" in content:
            return ScriptLogStatus.SUCCESS
        return ScriptLogStatus.FAILED

    def parse_daily(self, content: str) -> bool | None:
        if "Daily Task Completed" in content:
            return True
        if "Daily Task exception stopped" in content:
            return False
        return None

    def parse_exit(self, content: str) -> bool | None:
        if (
            "Successfully Executed Task, Exiting Game and App!" in content
            or "ok:quit app" in content
            or "Window closed" in content
        ):
            return True
        return False


class OkNteLogParser(BaseLogParser):
    script_name = "ok-nte"
    # 仅取剩余体力数字（当前体力），不记录其它。
    stamina_pattern = r"info_set 当前体力 (\d+)"
    # 战斗复检 / 关机收尾产生的 ERROR 属良性噪声，不计入报错。
    error_markers = ("ERROR",)
    error_noise = (
        "target_enemy failed",  # 战斗复检，可自行恢复
        "Failed to terminate process",  # 关机收尾
    )

    def _get_log_dir(self, script_path: str) -> Path:
        ok_nte_dir = Path(script_path).parent
        return ok_nte_dir / "data" / "apps" / "ok-nte" / "working" / "logs"

    def _get_log_pattern(self) -> str:
        return "ok-script.log"

    def parse_content(self, content: str) -> str:
        if "Successfully Executed Task" in content or "Task completed" in content:
            return ScriptLogStatus.SUCCESS
        return ScriptLogStatus.FAILED

    def parse_daily(self, content: str) -> bool | None:
        if "结束执行日常任务" not in content:
            return None
        # info_set failed [] 表示无失败项；否则（含失败任务）视为未完全完成。
        if "info_set failed []" in content:
            return True
        return False

    def parse_exit(self, content: str) -> bool | None:
        if (
            "Successfully Executed Task, Exiting Game and App!" in content
            or "ok:quit app" in content
        ):
            return True
        return False


class OkEfLogParser(BaseLogParser):
    script_name = "ok-ef"
    # 日志为结构化汇总报告：无体力数字；报错以「- 」缩进明细行列出。
    # 不设 stamina_pattern（为空），故 parse_stamina 返回 None。

    def _get_log_dir(self, script_path: str) -> Path:
        return Path(tempfile.gettempdir()) / "ok-ef" / "日常任务"

    def _get_log_pattern(self) -> str:
        return "日常任务_*.txt"

    def parse_content(self, content: str) -> str:
        if "执行状态: 完成" in content:
            return ScriptLogStatus.SUCCESS
        return ScriptLogStatus.FAILED

    def parse_daily(self, content: str) -> bool | None:
        if "执行状态: 完成" in content:
            return True
        if "执行状态: 部分失败" in content or "执行状态: 异常结束" in content:
            return False
        return None

    def parse_exit(self, content: str) -> bool | None:
        # 完成 / 部分失败 → 已正常跑完整轮；异常结束 / 运行中 → 异常退出。
        if "执行状态: 完成" in content or "执行状态: 部分失败" in content:
            return True
        return False

    def collect_error_lines(self, content: str, limit: int = 10) -> list[str]:
        # 报告中的失败明细以缩进的「- 」列表项给出，直接收集这些行。
        errors: list[str] = []
        for line in content.splitlines():
            s = line.strip()
            if s.startswith("- ") and len(s) > 2:
                errors.append(s)
                if len(errors) >= limit:
                    break
        return errors


class M7ALogParser(BaseLogParser):
    script_name = "March7th-Assistant"  # 由 script_path(含空格) 的 get_script_name 推导
    # 仅取剩余开拓力数字，不记录总体力。
    stamina_pattern = r"开拓力[：:]\s*(\d+)/(\d+)"
    error_markers = ("ERROR",)

    def _get_log_dir(self, script_path: str) -> Path:
        m7a_dir = Path(script_path).parent
        return m7a_dir / "logs"

    def _get_log_pattern(self) -> str:
        return "*.log"

    def parse_content(self, content: str) -> str:
        # 游戏正常终止后，助手还会做收尾善后（如「获取培养目标」），
        # 此时游戏窗口已关闭，会固定产生 WinError 233 / 截图失败 等报错。
        # 这些「终止后」的报错属良性，不应计入当日成败，只统计终止之前的报错。
        term_idx = content.rfind("游戏终止")
        if term_idx < 0:
            # 没有「游戏终止」标记：游戏未正常结束（很可能超时 / 被强杀），判失败。
            return ScriptLogStatus.FAILED
        body = content[:term_idx]
        if body.count("ERROR") <= 1:
            return ScriptLogStatus.SUCCESS
        return ScriptLogStatus.FAILED

    def _error_body(self, content: str) -> str:
        # 游戏正常终止后的收尾报错属良性，报错收集同样截断到「游戏终止」之前。
        term_idx = content.rfind("游戏终止")
        if term_idx < 0:
            return content
        return content[:term_idx]

    def parse_daily(self, content: str) -> bool | None:
        if "每日实训已完成" in content:
            return True
        return None

    def parse_exit(self, content: str) -> bool | None:
        if "游戏终止" in content:
            return True
        return False


class ZZZLogParser(BaseLogParser):
    script_name = "OneDragon-Launcher"
    # 仅取剩余电量数字，不记录储蓄电量 / 以太电池。
    stamina_pattern = r"剩余电量 (\d+) 储蓄电量 (\d+) 以太电池 (\d+)"
    error_markers = ("[ERROR]",)
    # 仅「指令[ 等待大世界画面 ] 执行失败 返回状态 未到达大世界」这一具体重试瞬时错误
    # 计入会误报 WARN（整轮仍以「一条龙 执行成功」收尾），故精确排除该噪声行。
    error_noise = ("指令[ 等待大世界画面 ] 执行失败 返回状态 未到达大世界",)

    def _get_log_dir(self, script_path: str) -> Path:
        zzz_dir = Path(script_path).parent
        return zzz_dir / ".log"

    def _get_log_pattern(self) -> str:
        return "log.txt"

    def parse_content(self, content: str) -> str:
        if (
            "指令[ 一条龙 ] 执行成功" in content
            or "指令[ 执行应用组 one_dragon ] 执行成功" in content
        ):
            return ScriptLogStatus.SUCCESS
        if "[ERROR]" in content:
            return ScriptLogStatus.FAILED
        return ScriptLogStatus.FAILED

    def parse_daily(self, content: str) -> bool | None:
        if (
            "指令[ 一条龙 ] 执行成功" in content
            or "指令[ 执行应用组 one_dragon ] 执行成功" in content
        ):
            return True
        if "执行失败" in content:
            return False
        return None

    def parse_exit(self, content: str) -> bool | None:
        if "返回状态 全部结束" in content or "关闭游戏成功" in content:
            return True
        return False


class BGILogParser(BaseLogParser):
    script_name = "BetterGI"
    # 仅取原粹树脂（剩余体力）数字，不记录浓缩树脂。
    stamina_pattern = r"原粹树脂：(\d+)，浓缩树脂：(\d+)"
    # 仅把显式报错标记纳入：用「异常:」(带冒号) 排除游戏内正常术语「地脉异常」等。
    error_markers = ("[ERR]", "异常:", "异常：")

    def _get_log_dir(self, script_path: str) -> Path:
        bgi_dir = Path(script_path).parent
        return bgi_dir / "log"

    def _get_log_pattern(self) -> str:
        return "better-genshin-impact*.log"

    def parse_content(self, content: str) -> str:
        if "一条龙和配置组任务结束" in content:
            if "未领取" in content:
                return ScriptLogStatus.FAILED
            return ScriptLogStatus.SUCCESS
        if "[ERR]" in content or "异常" in content:
            return ScriptLogStatus.FAILED
        return ScriptLogStatus.FAILED

    def parse_extra(self, content: str) -> str | None:
        # 原神特有：浓缩树脂非 0 时记录到额外信息（还有多少可换体力的储备）。
        m = re.findall(r"原粹树脂：(\d+)，浓缩树脂：(\d+)", content)
        if not m:
            return None
        conc = int(m[-1][1])
        if conc == 0:
            return None
        return f"浓缩树脂: {conc}"

    def parse_daily(self, content: str) -> bool | None:
        if "今日奖励已领取" in content:
            return True
        if "未领取" in content:
            return False
        return None

    def parse_exit(self, content: str) -> bool | None:
        if (
            "一条龙和配置组任务结束" in content
            or "主窗体退出" in content
            or "游戏已退出" in content
        ):
            return True
        return False


_PARSERS = [
    OkWwLogParser,
    OkNteLogParser,
    OkEfLogParser,
    M7ALogParser,
    BGILogParser,
    ZZZLogParser,
]


def parse_log(script_name: str, script_path: str = "") -> dict:
    """解析单个脚本当日日志：按 script_name 找到对应 Parser 并解析，返回统一结构。

    返回 dict 恒含 status / log_path / log_content / stamina / daily_done / exited /
    errors / extra 八键；无日志（NO_LOG）为缺省值，使消费方直接 d[key]。
    script_name 必为受支持脚本（parse_logs 入口已过滤），不支持即不可能。
    """
    # 不支持的脚本在 parse_logs 入口已过滤，到此处即不可能。
    supported_names = {cls.script_name for cls in _PARSERS if cls.script_name}
    assert script_name in supported_names, f"不支持的脚本不应进入 parse_log: {script_name}"
    for parser_cls in _PARSERS:
        if script_name == parser_cls.script_name:
            result = parser_cls().parse(script_path)
            # parse() 在 NO_LOG 时只返 status/log_path（四类字段缺省），补全缺省值使结构统一；
            # 仅对缺省键 setdefault，不覆盖调用方（如测试）已提供的字段。
            if "stamina" not in result:
                result.setdefault("log_content", "")
                result.setdefault("stamina", None)
                result.setdefault("daily_done", False)
                result.setdefault("exited", _resolve_exited(None, result["status"]))
                result.setdefault("errors", [])
                result.setdefault("extra", None)
            return result


def _prepare_action_lists(entries: list[dict]) -> tuple[list[str], list[str]]:
    """准备需处理脚本的标识列表，供下游自动化：

    - rerun:  未正常退出（exited 不为 True，含无日志），供 rerun.py 重跑；
    - notify: 存在报错日志（errors 非空），供 notify_mail.py 发邮件。
    """
    rerun_list = []
    notify_list = []
    for entry in entries:
        result = entry["result"]
        # 重跑依据=未正常退出；通知依据=有报错。两轴独立，可同时触发于同一脚本。
        if result["exited"] is not True:
            rerun_list.append(entry["script_name"])
        if result["errors"]:
            notify_list.append(entry["script_name"])
    return rerun_list, notify_list


def _format_diagnostic_sections(entries: list[dict], collapse_fn=None) -> str:
    """生成「各脚本报错明细」+「各脚本日志尾部」两段诊断文本（固定顺序），供控制台与邮件复用。

    第一段覆盖 errors 非空的脚本（含 WARN「有报错」与 FAILED），打印各脚本报错信息；
    第二段仅覆盖 FAILED 脚本，打印日志尾部（深入排查失败原因）；报错信息整体位于日志尾部之前。
    log_info 打印，邮件调用方拼入正文（并传入 collapse_fn 折叠连续重复行防刷屏）。
    """
    error_entries = [e for e in entries if e["result"]["errors"]]
    failed_entries = [e for e in entries if e["result"]["status"] == ScriptLogStatus.FAILED]
    if not error_entries and not failed_entries:
        return ""
    lines: list[str] = []
    if error_entries:
        # 第一段：各脚本出错的信息。
        lines.append("=" * 60)
        lines.append("各脚本报错明细")
        lines.append("=" * 60)
        for entry in error_entries:
            result = entry["result"]
            # 正常完成但含报错 → WARN「有报错」，与汇总表格呈现一致。
            display_status = (
                ScriptLogStatus.WARN
                if (result["status"] == ScriptLogStatus.SUCCESS and result["errors"])
                else result["status"]
            )
            # 展示状态均已纳入 status_cn；未覆盖即属不可能。
            assert display_status in status_cn, f"未覆盖的展示状态: {display_status}"
            lines.append("")
            lines.append(f"[{entry['display_name']}] 状态: {status_cn[display_status]}")
            if result["log_path"]:
                lines.append(f"日志路径: {result['log_path']}")
            lines.append("报错日志:")
            for err in result["errors"]:
                lines.append(f"  - {err}")
    if failed_entries:
        # 第二段：各脚本日志尾部（仅 FAILED，置于报错信息全部结束之后）。
        lines.append("")
        lines.append("=" * 60)
        lines.append("各脚本日志尾部")
        lines.append("=" * 60)
        for entry in failed_entries:
            log_content = entry["result"]["log_content"]
            if not log_content:
                continue
            tail = "\n".join(log_content.splitlines()[-_LOG_TAIL_LINES:])
            if collapse_fn is not None:
                tail = collapse_fn(tail)
            lines.append("")
            lines.append(f"[{entry['display_name']}] 日志尾部:")
            lines.append(tail)
    return "\n".join(lines)


def _build_summary_report(
    entries: list[dict], rerun_list: list[str], notify_list: list[str], do_log: bool
) -> str:
    """汇总表格文本：标题 / 表头 / 各脚本行 / 统计。report_lines 同时供邮件整表通知复用。"""
    headers = ["脚本", "状态", "剩余体力", "每日", "退出", "报错", "额外信息"]
    widths = [16, 8, 10, 6, 6, 6, 24]
    total = sum(widths)
    report_lines: list[str] = []

    def emit(line: str) -> None:
        report_lines.append(line)
        log_info(line, do_log=do_log)

    emit("=" * total)
    emit("脚本运行状况汇总报告")
    emit("=" * total)

    success_count = failed_count = no_log_count = 0
    for entry in entries:
        status = entry["result"]["status"]
        if status == ScriptLogStatus.SUCCESS:
            success_count += 1
        elif status == ScriptLogStatus.FAILED:
            failed_count += 1
        else:
            no_log_count += 1

    emit(_pad_row(headers, widths))
    emit("-" * total)
    for entry in entries:
        result = entry["result"]
        errors = result["errors"]
        # 显示状态：正常完成但含报错 → WARN「有报错」（仅呈现层，抓潜在问题）。
        display_status = (
            ScriptLogStatus.WARN
            if (result["status"] == ScriptLogStatus.SUCCESS and errors)
            else result["status"]
        )
        stamina = result["stamina"]
        daily = result["daily_done"]
        extra = result["extra"]
        exited = result["exited"]
        # 所有展示状态均已纳入 status_cn；未覆盖即属不可能，直接断言。
        assert display_status in status_cn, f"未覆盖的展示状态: {display_status}"
        emit(_pad_row([
            entry["display_name"],
            status_cn[display_status],
            str(stamina) if stamina is not None else "—",
            "是" if daily else "否",
            "是" if exited else "否",
            str(len(errors)),
            str(extra) if extra is not None else "—",
        ], widths))
    emit("=" * total)

    emit(
        f"总计: {success_count + failed_count + no_log_count} 个脚本"
        f" | 成功: {success_count} | 失败: {failed_count} | 无日志: {no_log_count}"
    )
    emit(f"将重跑: {len(rerun_list)} 个 | 将通知: {len(notify_list)} 个")

    # 末尾两段控制台明细（仅打印，不进 report 文本）：复用 _format_diagnostic_sections，
    # 与 notify_mail 邮件逐脚本详情同结构（报错信息在前、日志尾部在后）。
    if do_log:
        diagnostic = _format_diagnostic_sections(entries)
        if diagnostic:
            log_info("\n" + diagnostic, do_log=do_log)

    return "\n".join(report_lines)


def parse_logs(do_log: bool = True) -> dict[str, list[str] | str]:
    """汇总各脚本当日运行情况：收集解析结果，得到汇总表格并准备需处理脚本列表。

    按脚本唯一标识 script_name（exe=进程名 / python=display_name）匹配各 Parser；
    返回 dict：
      - "rerun":  未正常退出的脚本标识（含无日志），供 rerun.py 重跑；
      - "notify": 存在报错日志的脚本标识，供 notify_mail.py 发邮件；
      - "report": 汇总表格文本，供 notify_mail.py 整表通知；
      - "entries": 各脚本解析结果（含 display_name / result），供 notify_mail.py 复用诊断文本。
    表格状态列：正常完成但含报错显示为 WARN「有报错」，仅呈现层；
    rerun/notify 仍按 exited/errors 判定。
    do_log=False 时不打印报告。
    """
    _setup_logging()
    # Windows 控制台默认 GBK 编码，日志中可能含 emoji 等字符
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    config_path = Path(_get_root_dir()) / "config" / "config.yml"
    assert config_path.exists(), f"[log_monitor] config.yml 不存在: {config_path}"

    with open(config_path, encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}

    script_list = config_data.get("script_list", [])
    # 受支持脚本由各 parser 的 script_name 推导，与全链路标识一致。
    supported = {cls.script_name for cls in _PARSERS if cls.script_name}

    # 收集各脚本解析结果（parse_log 已按 script_name 找到对应 Parser 并解析）。
    entries = []
    for script in script_list:
        script_name = get_script_name(script)
        if not script_name or script_name not in supported:
            continue
        entries.append({
            "script_name": script_name,
            "display_name": script.get("display_name", script_name),
            "result": parse_log(script_name, script.get("script_path", "")),
        })

    rerun_list, notify_list = _prepare_action_lists(entries)
    report = _build_summary_report(entries, rerun_list, notify_list, do_log)

    return {"rerun": rerun_list, "notify": notify_list, "report": report, "entries": entries}


if __name__ == "__main__":
    # 仅收集并打印当日各脚本的运行日志（重跑由 rerun.py 负责）。
    parse_logs()
