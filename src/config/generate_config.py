"""首次启动配置生成（GUI-free）。

把「从模板复制生成 config/schedule/weekly」与「对齐各脚本 config」两类首启逻辑
收敛到一个无 PySide6 依赖的模块，使测试脚手架（tests/__init__.py）能在不导入
GUI 栈的前提下复用同一套首启产物，避免『本地有 config.yml、CI 无』的绿红不一致。
引入 PySide6 的调用方（main GUI 入口）改为 import 本模块。
"""

import os

from src.utils import (
    get_config_yml_path_under_root,
    get_root_dir,
    get_schedule_yml_path_under_root,
    get_weekly_yml_path_under_root,
    safe_path_join,
)
from src.utils.utils_yaml import dump_yaml, load_yaml


def generate_config_from_example() -> None:
    """从 config.example.yml 复制生成 config/config.yml。

    相对 script_path 保留原样，运行时由 resolve_script_path / get_script_path
    按项目根解析（配置可移植、跨机可用）。
    """
    example_path = safe_path_join(get_root_dir(), "config", "config.example.yml")
    config_path = get_config_yml_path_under_root()
    assert os.path.exists(example_path), f"[sub_config] 模板不存在: {example_path}"
    data = load_yaml(example_path)
    dump_yaml(config_path, data)


def generate_schedule_from_example() -> None:
    """从 config/schedule.example.yml 复制生成 config/schedule.yml。

    调度运行参数（shutdown / timed_run / mute / rerun / notify）独立于 config.yml，
    与脚本链声明（script_list）解耦；首次运行时由 ``config_workflow`` 与 config.yml
    一并生成。模板见 config/schedule.example.yml。
    """
    example_path = safe_path_join(get_root_dir(), "config", "schedule.example.yml")
    schedule_path = get_schedule_yml_path_under_root()
    assert os.path.exists(example_path), f"[sub_config] 模板不存在: {example_path}"
    data = load_yaml(example_path)
    dump_yaml(schedule_path, data)


def generate_weekly_from_example() -> None:
    """从 config/weekly.example.yml 复制生成 config/weekly.yml。

    合并了运行期周常参数（weekly_start 周几起 + weekly_timeouts 每周超时）的用户文件，
    与静态周常声明（config/weekly_list.yml，进 git）解耦；首次运行时由
    ``config_workflow`` 与 config.yml / schedule.yml 一并生成。模板见
    config/weekly.example.yml。
    """
    example_path = safe_path_join(get_root_dir(), "config", "weekly.example.yml")
    weekly_path = get_weekly_yml_path_under_root()
    assert os.path.exists(example_path), f"[sub_config] 模板不存在: {example_path}"
    data = load_yaml(example_path)
    dump_yaml(weekly_path, data)


def config_workflow() -> None:
    """每次启动配置生成：缺失才从模板生成 config/schedule/weekly，并对齐各脚本 config。

    三者缺哪个补哪个，与 generate_*_from_example「缺失才生成」语义一致；
    随后 init_config_all() 对齐所有已注册脚本的 config 与模板（未安装脚本为空操作）。
    """
    config_path = get_config_yml_path_under_root()
    if not os.path.exists(config_path):
        generate_config_from_example()
    schedule_path = get_schedule_yml_path_under_root()
    if not os.path.exists(schedule_path):
        generate_schedule_from_example()
    weekly_path = get_weekly_yml_path_under_root()
    if not os.path.exists(weekly_path):
        generate_weekly_from_example()
    # 每次启动对齐所有已注册脚本的 config 与模板
    from src.config.set_config import init_config_all

    init_config_all()
