"""将本次运行的脚本日志截取并打包，用于邮件附件。"""

import io
import logging
import re
import zipfile

from src.utils.utils_sub_config import get_script_name, resolve_log_path

logger = logging.getLogger(__name__)
MAX_LOG_BYTES = 5 * 1024 * 1024


def _latest_file(pattern):
    if pattern is None:
        return None
    if not any(char in pattern.name for char in "*?["):
        return pattern if pattern.is_file() else None
    candidates = [path for path in pattern.parent.glob(pattern.name) if path.is_file()]
    return max(
        candidates, key=lambda path: (path.stat().st_mtime_ns, path.name), default=None
    )


def build_log_archive(scripts, selected_names):
    """返回 ZIP 字节；每个日志至多保留文件末尾 5 MiB。"""
    output = io.BytesIO()
    notes = ["日志附件：每个文件最多保留末尾 5 MiB；截取时首个字符或行可能不完整。"]
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, script in enumerate(scripts, 1):
            name = get_script_name(script)
            if name not in selected_names:
                continue
            label = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .") or "script"
            seen = set()
            for analysis, kind in ((False, "实时"), (True, "分析")):
                try:
                    path = _latest_file(resolve_log_path(script, analysis=analysis))
                    if path is None:
                        notes.append(f"{name} / {kind}：未找到日志")
                        continue
                    if path in seen:
                        continue
                    seen.add(path)
                    with path.open("rb") as log:
                        log.seek(0, 2)
                        size = log.tell()
                        log.seek(max(0, size - MAX_LOG_BYTES))
                        content = log.read(MAX_LOG_BYTES)
                    archive.writestr(f"{index:02d}-{label}/{kind}-{path.name}", content)
                    notes.append(
                        f"{name} / {kind}：{'已截取末尾 5 MiB' if size > MAX_LOG_BYTES else '完整'}"
                    )
                except (OSError, ValueError) as exc:
                    logger.warning("[mail] 日志打包失败 %s / %s：%s", name, kind, exc)
                    notes.append(f"{name} / {kind}：读取失败（{type(exc).__name__}）")
        archive.writestr("说明.txt", "\n".join(notes) + "\n")
    return output.getvalue()
