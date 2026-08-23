"""诊断入口：python -m src.log 打印当日各脚本运行汇总报告。

等价于旧 ``scripts/collect_log.py`` 的 CLI 行为（后者已随运行后动作体系内联进
``src/log`` 而移除）。仅作控制台诊断，不依赖 GUI/定时流程。
"""

import logging

from src.log.monitor import parse_logs

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parse_logs(do_log=True)
