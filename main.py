import sys
import os
import shutil
import subprocess

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "OneDragon-ScriptChainer", "src"))
from one_dragon.utils.os_utils import get_path_under_work_dir

def check_file_exists(path: str) -> bool:
    return os.path.exists(path)

def copy_config():
    chain_name = "99.yml"
    dir_path = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(dir_path, chain_name)
    output_path = get_path_under_work_dir("config", "script_chain")
    if not check_file_exists(os.path.join(output_path, chain_name)):
        shutil.copy(input_path, output_path)
        print(f"已复制配置文件到: {output_path}")

def copy_python_script(file_name):
    dir_path = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(dir_path, file_name)
    output_path = get_path_under_work_dir("config", "script_chain", "scripts")
    if not check_file_exists(os.path.join(output_path, file_name)):
        shutil.copy(input_path, output_path)
        print(f"已复制Python脚本到: {output_path}")

if __name__ == "__main__":
    copy_config()
    #copy_python_script() TODO: add python script

    launcher_work_dir = get_path_under_work_dir("src")
    command = [
        sys.executable,
        "-m",
        "script_chainer.win_exe.launcher",
    ]
    res = subprocess.run(
        command,
        cwd=launcher_work_dir,
    )
