import sys
import os
import shutil
import subprocess
import datetime
import argparse

import config_ui

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "OneDragon-ScriptChainer", "src"))
from one_dragon.utils.os_utils import get_path_under_work_dir as get_path_under_odsc

BaseDIR = os.path.dirname(os.path.abspath(__file__))
PyScriptDir = os.path.join(BaseDIR, "python_script")

def ensure_base_configs_exist():
    template_path = os.path.join(BaseDIR, "01.yml")
    for i in range(1, 8):
        target_path = os.path.join(BaseDIR, f"{i:02d}.yml")
        if not os.path.exists(target_path) and os.path.exists(template_path):
            shutil.copy(template_path, target_path)

def copy_configs():
    output_dir = get_path_under_odsc("config", "script_chain")
    os.makedirs(output_dir, exist_ok=True)
    for i in range(1, 8):
        chain_name = f"{i:02d}.yml"
        input_path = os.path.join(BaseDIR, chain_name)
        output_path = os.path.join(output_dir, chain_name)
        if os.path.exists(input_path) and not os.path.exists(output_path):
            shutil.copy(input_path, output_path)
            print(f"已复制配置文件到: {output_path}")

def is_any_config_exist():
    config_dir = get_path_under_odsc("config", "script_chain")
    if not os.path.exists(config_dir):
        return False
    for i in range(1, 8):
        if os.path.exists(os.path.join(config_dir, f"{i:02d}.yml")):
            return True
    return False

def copy_python_scripts():
    file_names = [f for f in os.listdir(PyScriptDir) if f.endswith(".py")]
    for file_name in file_names:
        input_path = os.path.join(PyScriptDir, file_name)
        output_path = get_path_under_odsc("config", "script_chain", "scripts")
        os.makedirs(output_path, exist_ok=True)
        if not os.path.exists(os.path.join(output_path, file_name)):
            shutil.copy(input_path, output_path)
            print(f"已复制Python脚本{file_name}到: {output_path}")

def launcher(args):
    launcher_work_dir = get_path_under_odsc("src")
    command = [
        sys.executable,
        "-m",
        "script_chainer.win_exe.launcher",
    ]
    if args.onedragon:
        command.append("--onedragon")
        if args.chain:
            command.extend(["--chain", args.chain])
        else:
            day = datetime.datetime.now().isoweekday()
            command.extend(["--chain", f"{day:02d}"])

    res = subprocess.run(
        command,
        cwd=launcher_work_dir,
    )
    return res.returncode

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OneDragon Helper")
    parser.add_argument("--onedragon", action="store_true", help="Run script chain automatically")
    parser.add_argument("--chain", type=str, help="Script chain to run (e.g., 01, 02)")
    args, unknown = parser.parse_known_args()

    ensure_base_configs_exist()

    if not is_any_config_exist():
        copy_python_scripts()
        config_ui.run_config_ui()
        copy_configs()
    else:
        copy_configs()
        copy_python_scripts()

    launcher(args)
