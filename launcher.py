import subprocess
import sys
import os
import yaml
import copy
from datetime import datetime

from utils import get_path_under_onedragon, get_config_yml_path_under_root, get_weekly_timeouts_yml_path_under_root

def get_week_num() -> int:
    """
    返回星期数字：0周一 ~ 6周日
    :return: int
    """
    return datetime.now().weekday()

def generate_OneDragon_script_chain() -> None:
    """
    复制OneDragon-ScriptChainer到script_chain目录
    :return: None
    """
    def get_output_file_path() -> str:
        output_dir = get_path_under_onedragon("config", "script_chain")
        chain_name = f"01.yml"
        return os.path.join(output_dir, chain_name)

    with open(get_config_yml_path_under_root(), 'r', encoding='utf-8') as f:
        config_data = yaml.safe_load(f)

    # 从独立的 weekly_timeouts.yml 读取每周超时配置
    weekly_timeouts_path = get_weekly_timeouts_yml_path_under_root()
    weekly_timeouts_map = {}
    if os.path.exists(weekly_timeouts_path):
        with open(weekly_timeouts_path, 'r', encoding='utf-8') as f:
            weekly_timeouts_map = yaml.safe_load(f) or {}

    # 遍历每个脚本，根据当前星期，更新超时时间配置
    data_copy = copy.deepcopy(config_data)
    for script in data_copy.get('script_list', []):
        display_name = script.get('display_name', '')
        timeouts = weekly_timeouts_map.get(display_name, None)
        if timeouts:
            assert len(timeouts) == 7, f"weekly_timeouts 长度错误 ({display_name})，当前长度为 {len(timeouts)}"
            script['run_timeout_seconds'] = timeouts[get_week_num()]
        print(f"[{script['display_name']}] 的超时时间为 {script['run_timeout_seconds']} 秒")

    # 将新的配置写入配置文件
    output_file_path = get_output_file_path()
    with open(output_file_path, 'w', encoding='utf-8') as f:
        yaml.dump(data_copy, f, allow_unicode=True, sort_keys=False)
    
    return

def run_launcher():
    """
    运行OneDragon-ScriptChainer
    :return: int
    """
    launcher_work_dir = get_path_under_onedragon("src")
    command = [
        sys.executable,
        "-m",
        "script_chainer.win_exe.launcher",
    ]
    res = subprocess.run(
        command,
        cwd=launcher_work_dir,
    )
    return res.returncode

if __name__ == "__main__":
    generate_OneDragon_script_chain()
    run_launcher()
