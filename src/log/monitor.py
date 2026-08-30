"""
各游戏脚本运行日志的解析与汇总。

每款游戏对应一个 `*LogParser` 子类，从其日志判定运行结果（成功 / 失败 / 无日志）；
`parse_log` 按 script_name 找到对应 Parser 并解析单个脚本；`parse_logs` 先收集各脚本解析
结果，再分别由 `_build_summary_report` 生成汇总表格、`_prepare_action_lists` 准备需处理脚本列表
（重跑 / 通知）。失败重跑由同目录 `rerun.py`、报错邮件由同目录 `notify_mail.py` 负责，二者均调用
本文件 `parse_logs`（后者复用其返回的汇总表格做整表通知）。

本模块为 `src.log` 包的子模块，由 `python -m src.log`（__main__ 入口）或 GUI/service 以 `import
src.log.monitor` 方式调用，不单独运行。除复用脚本唯一标识 `get_script_name`（见
`src.config.subscript`）外，不依赖项目内其余模块；根目录由 `_get_root_dir` 推导，并直接
读取 `config.yml`（经 `src.utils_yaml.load_yaml`，ruamel YAML 1.2 解析）。
"""

import logging
import os
import re
import sys
import tempfile
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from src.config.subscript import get_script_name
from src.utils_logger import setup_logging
from src.utils_yaml import load_yaml, load_yaml_optional

logger = logging.getLogger(__name__)


def log_info(msg, *args, do_log: bool = True) -> None:
    """统一日志打印入口；do_log=False 时静默。"""
    if do_log:
        logger.info(msg, *args)


def _get_root_dir() -> str:
    """推导项目根目录（向上 3 层：src/log/monitor.py → 项目根）。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# 项目根在模块导入时捕获一次：日志分析关键词配置（config/log_analysis.yml）属项目级
# 静态配置，测试中对 _get_root_dir 的 patch（仅针对 config.yml）不应影响它的读取路径。
_PROJECT_ROOT = _get_root_dir()

_LOG_ANALYSIS_YAML = "log_analysis.yml"
# 缓存：配置文件小而稳定，进程内只解析一次。global 仅在模块内使用。
_LOG_ANALYSIS_CONFIG: dict | None = None


def _load_log_analysis_config() -> dict:
    """读取 config/log_analysis.yml（可选文件，缺失返回空 dict）。结果进程内缓存。"""
    global _LOG_ANALYSIS_CONFIG
    if _LOG_ANALYSIS_CONFIG is None:
        path = os.path.join(_PROJECT_ROOT, "config", _LOG_ANALYSIS_YAML)
        _LOG_ANALYSIS_CONFIG = load_yaml_optional(path)
    return _LOG_ANALYSIS_CONFIG


def _keywords_for(script_name: str) -> dict:
    """取某脚本的日志分析关键词配置；缺失即断言失败（配置遗漏属编程错误，快速暴露）。"""
    cfg = _load_log_analysis_config()
    parsers = cfg.get("parsers", {})
    assert script_name in parsers, f"[log_monitor] 缺少日志分析配置: {script_name}"
    return parsers[script_name]


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


_LOG_TAIL_LINES = 200


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
    ScriptLogStatus.WARN: "警告",
}


class BaseLogParser:
    # 脚本唯一标识（与全链路一致，见 src.config.subscript.get_script_name）：
    # exe 脚本=进程名（script_path basename 去后缀，空格→-），python 脚本=display_name。
    # parse_log 与 supported 推导都按它匹配，不再依赖易变的 display_name。
    script_name: str = ""
    # 以下判定关键词（含成功 / 失败 / 退出 / 体力提取正则 / 日志文件名）均来自
    # config/log_analysis.yml，由 __init__ 经 _apply_keywords 注入；此处仅留类型与缺省，
    # 真正的取值以配置文件为准。具体语义见 log_analysis.yml 顶部注释。
    # 判定某行是否为报错的子串标记。
    error_markers: tuple[str, ...] = ("ERROR",)
    # 命中 error_markers 但实为良性噪声（启动瞬断 / 战斗复检 / 关机收尾等）的子串，
    # 含这些子串的行不计入报错。
    error_noise: tuple[str, ...] = ()
    # 日志文件名 glob 模式（各子类按需覆写）。
    log_pattern: str = ""
    # 体力提取正则：第一个捕获组为剩余体力数字；不设置（为空）表示日志不含体力。
    stamina_pattern: str = ""
    # 判定当日是否做完的「成功」标记；命中任一即视为做完，否则（含未提及）视为未完成。
    daily_success_marker: tuple[str, ...] = ()
    # 终止横幅标记（崩铁用于截断「游戏终止」之后的良性报错），命中任一取其最后位置。
    exit_markers: tuple[str, ...] = ()
    # parse_content 成功 / 失败判定词（success 命中即 SUCCESS；部分游戏还有 fail 排除词）。
    # 默认空，由配置注入；各 Parser 的 parse_content 读取之。
    success_markers: tuple[str, ...] = ()
    fail_markers: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._apply_keywords()

    def _apply_keywords(self) -> None:
        """从 config/log_analysis.yml 注入本脚本的判定关键词；缺失字段以空值兜底。"""
        kw = _keywords_for(self.script_name)
        self.log_pattern = kw.get("log_pattern", "")
        self.stamina_pattern = kw.get("stamina_pattern", "")
        self.error_markers = tuple(kw.get("error_markers", ()))
        self.error_noise = tuple(kw.get("error_noise", ()))
        self.daily_success_marker = tuple(kw.get("daily_success_marker", ()))
        self.exit_markers = tuple(kw.get("exit_markers", ()))
        self.success_markers = tuple(kw.get("success_markers", ()))
        self.fail_markers = tuple(kw.get("fail_markers", ()))

    def get_log_path(self, script_path: str) -> Path | None:
        log_dir = self._get_log_dir(script_path)
        if not log_dir or not log_dir.exists():
            return None

        log_files = sorted(log_dir.glob(self.log_pattern), reverse=True)
        for log_file in log_files:
            if self._is_valid_log(log_file):
                return log_file
        return None

    def _get_log_dir(self, script_path: str) -> Path:
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

        # 运行日从 04:00 切分（定时运行在 04:10）：
        # - 现在 >= 4 点：认「今天 04:00 之后」产生的日志；
        # - 现在 < 4 点（凌晨）：认「昨天运行日」，即「昨天 04:00 之后」产生的日志。
        # 无后缀 log.txt 的 mtime 无法区分「昨天 04:00 后那轮」与更早的，但按运行日
        # 边界统一以 4 点为界，凌晨不会把今天 0-4 点之前的日志误当成今天。
        today_4am = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if now.hour >= 4:
            return mtime >= today_4am

        yesterday_4am = (now - timedelta(days=1)).replace(
            hour=4, minute=0, second=0, microsecond=0
        )
        return mtime >= yesterday_4am

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

    def parse_daily(self, content: str) -> bool:
        """当日每日是否做完：命中任一成功标记=True，否则=False（无标记即失败）。

        未配 ``daily_success_marker`` 的脚本无法判定，返回 True：若返回 False，
        重跑判据（日常没做完即重跑）会让它每次都进重跑名单。
        """
        if not self.daily_success_marker:
            return True
        return any(m in content for m in self.daily_success_marker)

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
        # daily_done 直接由 parse_daily 定稿：命中成功标记=True，否则=False（无标记即失败），
        # parse_daily 恒返 bool，无需再按 status 兜底。
        daily_done = self.parse_daily(content)
        return {
            "status": status,
            "log_path": str(log_path),
            "log_content": content[-2000:] if len(content) > 2000 else content,
            # 四类补充信息，向后兼容：旧消费者只用 status/log_path/log_content。
            "stamina": self.parse_stamina(content),
            "daily_done": daily_done,
            "errors": self.collect_error_lines(content),
            "extra": self.parse_extra(content),
        }


class OkWwLogParser(BaseLogParser):
    script_name = "ok-ww"

    def _get_log_dir(self, script_path: str) -> Path:
        ok_ww_dir = Path(script_path).parent
        return ok_ww_dir / "data" / "apps" / "ok-ww" / "working" / "logs"

    def parse_content(self, content: str) -> str:
        if any(m in content for m in self.success_markers):
            return ScriptLogStatus.SUCCESS
        return ScriptLogStatus.FAILED


class OkNteLogParser(BaseLogParser):
    script_name = "ok-nte"

    def _get_log_dir(self, script_path: str) -> Path:
        ok_nte_dir = Path(script_path).parent
        return ok_nte_dir / "data" / "apps" / "ok-nte" / "working" / "logs"

    def parse_content(self, content: str) -> str:
        if any(m in content for m in self.success_markers):
            return ScriptLogStatus.SUCCESS
        return ScriptLogStatus.FAILED


class OkEfLogParser(BaseLogParser):
    script_name = "ok-ef"

    def _get_log_dir(self, script_path: str) -> Path:
        return Path(tempfile.gettempdir()) / "ok-ef" / "日常任务"

    def parse_content(self, content: str) -> str:
        if any(m in content for m in self.success_markers):
            return ScriptLogStatus.SUCCESS
        return ScriptLogStatus.FAILED

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

    def _term_index(self, content: str) -> int:
        """返回最后一个终止横幅的位置；候选皆无则返回 -1。

        终止横幅即 exit_markers，复用之——
        取最后出现位置作为「游戏终止」分界点，截断其后的良性收尾报错。
        """
        idx = -1
        for marker in self.exit_markers:
            pos = content.rfind(marker)
            if pos > idx:
                idx = pos
        return idx

    def _get_log_dir(self, script_path: str) -> Path:
        m7a_dir = Path(script_path).parent
        return m7a_dir / "logs"

    def parse_content(self, content: str) -> str:
        # 游戏正常终止后，助手还会做收尾善后（如「获取培养目标」），
        # 此时游戏窗口已关闭，会固定产生 WinError 233 / 截图失败 等报错。
        # 这些「终止后」的报错属良性，不应计入当日成败，只统计终止之前的报错。
        term_idx = self._term_index(content)
        if term_idx < 0:
            # 没有任何终止横幅：游戏未正常结束（很可能超时 / 被强杀），判失败。
            return ScriptLogStatus.FAILED
        body = content[:term_idx]
        # 终止横幅之前每出现一个 error_markers 计一次；阈值沿用原判定（<=1 即成功）。
        if sum(body.count(m) for m in self.error_markers) <= 1:
            return ScriptLogStatus.SUCCESS
        return ScriptLogStatus.FAILED

    def _error_body(self, content: str) -> str:
        # 游戏正常终止后的收尾报错属良性，报错收集同样截断到终止横幅之前。
        term_idx = self._term_index(content)
        if term_idx < 0:
            return content
        return content[:term_idx]


class ZZZLogParser(BaseLogParser):
    script_name = "OneDragon-Launcher"

    def _get_log_dir(self, script_path: str) -> Path:
        zzz_dir = Path(script_path).parent
        return zzz_dir / ".log"

    def parse_content(self, content: str) -> str:
        if any(m in content for m in self.success_markers):
            return ScriptLogStatus.SUCCESS
        if any(m in content for m in self.error_markers):
            return ScriptLogStatus.FAILED
        return ScriptLogStatus.FAILED


class BGILogParser(BaseLogParser):
    script_name = "BetterGI"

    def _get_log_dir(self, script_path: str) -> Path:
        bgi_dir = Path(script_path).parent
        return bgi_dir / "log"

    def parse_content(self, content: str) -> str:
        if any(m in content for m in self.success_markers):
            if any(f in content for f in self.fail_markers):
                return ScriptLogStatus.FAILED
            return ScriptLogStatus.SUCCESS
        if any(m in content for m in self.error_markers):
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

    返回 dict 恒含 status / log_path / log_content / stamina / daily_done /
    errors / extra 七键；无日志（NO_LOG）为缺省值，使消费方直接 d[key]。
    script_name 必为受支持脚本（parse_logs 入口已过滤），不支持即不可能。
    """
    # 不支持的脚本在 parse_logs 入口已过滤，到此处即不可能。
    supported_names = {cls.script_name for cls in _PARSERS if cls.script_name}
    assert script_name in supported_names, (
        f"不支持的脚本不应进入 parse_log: {script_name}"
    )
    for parser_cls in _PARSERS:
        if script_name == parser_cls.script_name:
            result = parser_cls().parse(script_path)
            # parse() 在 NO_LOG 时只返 status/log_path（其余字段缺省），补全缺省值使结构统一；
            # 仅对缺省键 setdefault，不覆盖调用方（如测试）已提供的字段。
            if "stamina" not in result:
                result.setdefault("log_content", "")
                result.setdefault("stamina", None)
                result.setdefault("daily_done", False)
                result.setdefault("errors", [])
                result.setdefault("extra", None)
            return result


def _prepare_action_lists(entries: list[dict]) -> tuple[list[str], list[str]]:
    """准备需处理脚本的标识列表，供下游自动化：

    - rerun:  日常没做完（``daily_done`` 不为 True，含无日志），供 rerun.py 重跑；
    - notify: 存在报错日志（errors 非空），供 notify_mail.py 发邮件。

    只看日常、不看进程是否收尾：正常退出 ≠ 做完了。脚本完全可能跑完流程正常收尾、
    却一项日常都没做成（如 ok-ef「部分失败」仍会写退出标记），看退出会漏掉这类。
    """
    rerun_list = []
    notify_list = []
    for entry in entries:
        result = entry["result"]
        # 重跑依据=日常没做完；通知依据=有报错。两轴独立，可同时触发于同一脚本。
        if result["daily_done"] is not True:
            rerun_list.append(entry["script_name"])
        if result["errors"]:
            notify_list.append(entry["script_name"])
    return rerun_list, notify_list


def format_diagnostic_sections(entries: list[dict], collapse_fn=None) -> str:
    """生成「各脚本报错明细」+「各脚本日志尾部」两段诊断文本（固定顺序），供控制台与邮件复用。

    第一段覆盖 errors 非空的脚本（含 WARN「警告」与 FAILED），打印各脚本报错信息；
    第二段仅覆盖 FAILED 脚本，打印日志尾部（深入排查失败原因）；报错信息整体位于日志尾部之前。
    log_info 打印，邮件调用方拼入正文（并传入 collapse_fn 折叠连续重复行防刷屏）。
    """
    error_entries = [e for e in entries if e["result"]["errors"]]
    failed_entries = [
        e for e in entries if e["result"]["status"] == ScriptLogStatus.FAILED
    ]
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
            # 正常完成但含报错 → WARN「警告」，与汇总表格呈现一致。
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
    headers = ["脚本", "状态", "剩余体力", "每日", "报错", "额外信息"]
    widths = [16, 8, 10, 6, 6, 24]
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
        # 显示状态：正常完成但含报错 → WARN「警告」（仅呈现层，抓潜在问题）。
        display_status = (
            ScriptLogStatus.WARN
            if (result["status"] == ScriptLogStatus.SUCCESS and errors)
            else result["status"]
        )
        stamina = result["stamina"]
        daily = result["daily_done"]
        extra = result["extra"]
        # 所有展示状态均已纳入 status_cn；未覆盖即属不可能，直接断言。
        assert display_status in status_cn, f"未覆盖的展示状态: {display_status}"
        emit(
            _pad_row(
                [
                    entry["display_name"],
                    status_cn[display_status],
                    str(stamina) if stamina is not None else "—",
                    "是" if daily else "否",
                    str(len(errors)),
                    str(extra) if extra is not None else "—",
                ],
                widths,
            )
        )
    emit("=" * total)

    emit(
        f"总计: {success_count + failed_count + no_log_count} 个脚本"
        f" | 成功: {success_count} | 失败: {failed_count} | 无日志: {no_log_count}"
    )
    emit(f"将重跑: {len(rerun_list)} 个 | 将通知: {len(notify_list)} 个")

    # 末尾两段控制台明细（仅打印，不进 report 文本）：复用 format_diagnostic_sections，
    # 与 notify_mail 邮件逐脚本详情同结构（报错信息在前、日志尾部在后）。
    if do_log:
        diagnostic = format_diagnostic_sections(entries)
        if diagnostic:
            log_info("\n" + diagnostic, do_log=do_log)

    return "\n".join(report_lines)


def parse_logs(
    do_log: bool = True, candidate_script_names: set[str] | None = None
) -> dict[str, list[str] | str]:
    """汇总各脚本当日运行情况：收集解析结果，得到汇总表格并准备需处理脚本列表。

    按脚本唯一标识 script_name（exe=进程名 / python=display_name）匹配各 Parser；
    返回 dict：
      - "rerun":  日常没做完的脚本标识（含无日志），供 rerun.py 重跑；
      - "notify": 存在报错日志的脚本标识，供 notify_mail.py 发邮件；
      - "report": 汇总表格文本，供 notify_mail.py 整表通知；
      - "entries": 各脚本解析结果（含 display_name / result），供 notify_mail.py 复用诊断文本。
    表格状态列：正常完成但含报错显示为 WARN「警告」，仅呈现层；
    rerun/notify 仍按 daily_done/errors 判定。

    Args:
        candidate_script_names: 候选脚本标识集合（即本次启用的脚本）。传入后只在该
            集合内解析日志、挑选「需重跑/需通知」的脚本，根本不去碰未启用脚本
            的日志（无需事后取交集）。None 或空集合表示不纳入任何脚本——跳过解析、
            直接返回空结果（调用方想全量时显式传入 config 全部脚本集合）。
    do_log=False 时不打印报告。
    """
    # None/空集合 = 不干活：跳过日志解析，返回空结果。
    if not candidate_script_names:
        return {"rerun": [], "notify": [], "report": "", "entries": []}
    setup_logging()
    # Windows 控制台默认 GBK 编码，日志中可能含 emoji 等字符
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    config_path = Path(_get_root_dir()) / "config" / "config.yml"
    assert config_path.exists(), f"[log_monitor] config.yml 不存在: {config_path}"

    config_data = load_yaml(str(config_path))

    script_list = config_data.get("script_list", [])
    # 受支持脚本由各 parser 的 script_name 推导，与全链路标识一致。
    supported = {cls.script_name for cls in _PARSERS if cls.script_name}

    # 收集各脚本解析结果（parse_log 已按 script_name 找到对应 Parser 并解析）。
    entries = []
    for script in script_list:
        script_name = get_script_name(script)
        if not script_name or script_name not in supported:
            continue
        # 仅解析候选脚本：未启用的脚本不进入本次重跑/邮件的挑选范围。
        if script_name not in candidate_script_names:
            continue
        entries.append(
            {
                "script_name": script_name,
                "display_name": script.get("display_name", script_name),
                "result": parse_log(script_name, script.get("script_path", "")),
            }
        )

    rerun_list, notify_list = _prepare_action_lists(entries)
    report = _build_summary_report(entries, rerun_list, notify_list, do_log)

    return {
        "rerun": rerun_list,
        "notify": notify_list,
        "report": report,
        "entries": entries,
    }


def get_log_dir(script_name: str, script_path: str) -> Path | None:
    """按脚本标识找到对应 Parser，计算其日志目录；无匹配返回 None。

    供 GUI「打开日志」等场景复用，避免 GUI 手抄各游戏日志目录规则。
    script_path 应为绝对路径（与 config/script_path 一致）。
    """
    for cls in _PARSERS:
        if cls.script_name == script_name:
            return cls()._get_log_dir(script_path)
    return None
