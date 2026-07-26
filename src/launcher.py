"""启动器入口：命令行解析、无界面直跑（计划任务模式）与 GUI 启动。

GUI 各部分在 src/gui 包中：state（状态持久化）、runner（后台运行）、
widgets（自定义控件）、dialogs（弹窗）、main_window（主窗口）。
"""
import argparse
import logging
import os
import sys

import yaml
from PySide6.QtWidgets import QApplication

from src.config.init_config import config_workflow, need_config_workflow
from src.gui.main_window import MainWindow
from src.gui.runner import run_chain_command
from src.gui.state import apply_weekly_timeout
from src.utils import (
    get_config_yml_path_under_root,
    get_path_under_onedragon,
    get_weekly_timeouts_yml_path_under_root,
    safe_path_join,
)
from src.utils_logger import setup_logging

logger = logging.getLogger(__name__)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="OneDragon 脚本启动器")
    parser.add_argument(
        "--no-set-config",
        action="store_true",
        help="计划任务模式：跳过 GUI 与各脚本内部 config 写入，直接按 config.yml 中已启用的脚本运行",
    )
    return parser.parse_args()


def run_direct(chain_name="88") -> int:
    """无界面直接运行（计划任务模式）。

    读取 config.yml，应用周超时覆盖后生成 ScriptChainer 配置并运行全部脚本，便于计划任务调用。
    """
    with open(get_config_yml_path_under_root(), encoding='utf-8') as f:
        data = yaml.safe_load(f)
    assert 'script_list' in data, "[launcher] config.yml 缺少 script_list 字段"

    weekly_timeouts = {}
    weekly_path = get_weekly_timeouts_yml_path_under_root()
    if os.path.exists(weekly_path):
        with open(weekly_path, encoding='utf-8') as f:
            weekly_timeouts = yaml.safe_load(f) or {}

    updated_scripts = []
    for script in data['script_list']:
        apply_weekly_timeout(script, weekly_timeouts)
        updated_scripts.append(script)

    if not updated_scripts:
        logger.warning("[launcher] 没有可运行的脚本（script_list 为空），直接退出")
        return 0

    data['script_list'] = updated_scripts
    output_dir = get_path_under_onedragon("config", "script_chain")
    output_file = safe_path_join(output_dir, f"{chain_name}.yml")
    with open(output_file, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)

    return run_chain_command(chain_name)


def main():
    setup_logging()
    args = parse_args()
    if need_config_workflow():
        config_workflow()
    if args.no_set_config:
        sys.exit(run_direct("88"))
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
