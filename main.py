import sys
import os
import shutil
import subprocess

import config_ui

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "OneDragon-ScriptChainer", "src"))
from one_dragon.utils.os_utils import get_path_under_work_dir as get_path_under_odsc

BaseDIR = os.path.dirname(os.path.abspath(__file__))
PyScriptDir = os.path.join(BaseDIR, "python_script")
CHAIN_NAME = "01.yml"

def is_config_exist():
    config_path = get_path_under_odsc("config", "script_chain")
    return os.path.exists(os.path.join(config_path, CHAIN_NAME))

def copy_all_configs():
    output_dir = get_path_under_odsc("config", "script_chain")
    os.makedirs(output_dir, exist_ok=True)
    for i in range(1, 8):
        chain_name = f"{i:02d}.yml"
        input_path = os.path.join(BaseDIR, chain_name)
        output_path = os.path.join(output_dir, chain_name)
        if os.path.exists(input_path):
            shutil.copy(input_path, output_path)
            print(f"已复制配置文件到: {output_path}")

def copy_python_scripts():
    file_names = [f for f in os.listdir(PyScriptDir) if f.endswith(".py")]
    for file_name in file_names:
        input_path = os.path.join(PyScriptDir, file_name)
        output_path = get_path_under_odsc("config", "script_chain", "scripts")
        os.makedirs(output_path, exist_ok=True)
        if not os.path.exists(os.path.join(output_path, file_name)):
            shutil.copy(input_path, output_path)
            print(f"已复制Python脚本{file_name}到: {output_path}")

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
    if not is_config_exist():
        copy_python_scripts()
        config_ui.run_config_ui(CHAIN_NAME)
        copy_all_configs()
    else:
        # User might have regenerated configs manually
        copy_all_configs()
        copy_python_scripts()

    launcher()
