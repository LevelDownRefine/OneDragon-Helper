"""日志汇总 CLI 入口：核心解析逻辑见 `src.log` 包，本文件仅作命令行入口薄壳。

运行：python scripts/collect_log.py（仅收集并打印当日各脚本运行日志；
失败重跑由同目录 rerun.py、报错邮件由 notify_mail.py 负责，二者均调用 src.log.parse_logs）。
"""

import sys
from pathlib import Path

# 把项目根加入 sys.path，以便 import src.log。
_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.log import parse_logs  # noqa: E402

if __name__ == "__main__":
    parse_logs()
