import sys
import subprocess

from utils import get_path_under_onedragon
from config.generate_onedragon_config import config_workflow

def launcher():
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
    config_workflow()
    launcher()
