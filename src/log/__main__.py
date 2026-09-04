"""诊断入口：python -m src.log 打印当日各脚本运行汇总报告。

等价于旧 ``scripts/collect_log.py`` 的 CLI 行为（后者已随运行后动作体系内联进
``src/log`` 而移除）。仅作控制台诊断，不依赖 GUI/定时流程。
"""

import logging
from pathlib import Path

from src.log.monitor import parse_logs
from src.utils.utils_sub_config import get_script_name
from src.utils.utils_yaml import load_yaml

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # 诊断视图要覆盖全部脚本：显式传入 config 全部脚本集合（parse_logs 的 None/空
    # 集合语义是「跳过」，不表达「全部」）。
    config_path = Path(__file__).resolve().parents[2] / "config" / "config.yml"
    config_data = load_yaml(str(config_path))
    all_keys = {get_script_name(s) for s in config_data.get("script_list", [])}
    parse_logs(do_log=True, candidate_script_names=all_keys)
