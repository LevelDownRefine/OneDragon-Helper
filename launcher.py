import subprocess
import sys
import os
import yaml
import copy
from datetime import datetime

from utils import get_path_under_onedragon, get_root_dir

def get_week_num():
    """
    返回星期数字：0周一 ~ 6周日
    :return: int
    """
    return datetime.now().weekday()

def generate_OneDragon_script_chain():
    """
    复制OneDragon-ScriptChainer到script_chain目录
    :return: None
    """
    def get_output_file_path():
        output_dir = get_path_under_onedragon("config", "script_chain")
        chain_name = f"01.yml"
        return os.path.join(output_dir, chain_name)

    with open(os.path.join(get_root_dir(), "config.yml"), 'r', encoding='utf-8') as f:
        config_data = yaml.safe_load(f)

    i = get_week_num()
    data_copy = copy.deepcopy(config_data)
    for script in data_copy.get('script_list', []):
        timeouts = script.get('weekly_timeouts', None)
        if timeouts:
            assert len(timeouts) == 7, f"weekly_timeouts 长度错误，当前长度为 {len(timeouts)}"
            script['run_timeout_seconds'] = timeouts[i]
        print(f"[{script['display_name']}] 的超时时间为 {script['run_timeout_seconds']} 秒")

    output_file_path = get_output_file_path()
    with open(output_file_path, 'w', encoding='utf-8') as f:
        yaml.dump(data_copy, f, allow_unicode=True, sort_keys=False)

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
