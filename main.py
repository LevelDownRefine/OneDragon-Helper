import sys
import os
import shutil
import subprocess

import config_ui

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "OneDragon-ScriptChainer", "src"))
from one_dragon.utils.os_utils import get_path_under_work_dir as get_path_under_odsc

BaseDIR = os.path.dirname(os.path.abspath(__file__))

def copy_config():
    chain_name = "99.yml"
    input_path = os.path.join(BaseDIR, chain_name)
    output_path = get_path_under_odsc("config", "script_chain")
    if not os.path.exists(os.path.join(output_path, chain_name)):
        shutil.copy(input_path, output_path)
        print(f"已复制配置文件到: {output_path}")

def copy_python_script(file_name):
    input_path = os.path.join(BaseDIR, file_name)
    output_path = get_path_under_odsc("config", "script_chain", "scripts")
    if not os.path.exists(os.path.join(output_path, file_name)):
        shutil.copy(input_path, output_path)
        print(f"已复制Python脚本到: {output_path}")

def launcher():
    launcher_work_dir = get_path_under_odsc("src")
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
    copy_python_script("shutdown.py")
    config_ui.run_config_ui()
    copy_config()
    launcher()
