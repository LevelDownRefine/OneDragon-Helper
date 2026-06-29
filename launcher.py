from datetime import datetime
import subprocess
import sys

from utils import get_path_under_onedragon

def get_week_num():
    """
    返回星期数字：0周一 ~ 6周日
    :return: int
    """
    return datetime.now().weekday()

def get_chain_name():
    """
    返回链名称
    :return: str
    """
    return f"{get_week_num():02d}"

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
        "--onedragon", 
        "--chain", 
        get_chain_name(),
    ]
    res = subprocess.run(
        command,
        cwd=launcher_work_dir,
    )
    return res.returncode

if __name__ == "__main__":
    run_launcher()
