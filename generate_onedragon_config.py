import os
import shutil

from utils import get_path_under_onedragon, get_path_under_cwd, get_one_dragon_yml_path
from onedragon_config_ui import run_config_ui

def copy_all_configs():
    output_dir = get_path_under_onedragon("config", "script_chain")
    os.makedirs(output_dir, exist_ok=True)
    for i in range(1, 8):
        chain_name = f"{i:02d}.yml"
        input_path = get_path_under_cwd(chain_name)
        output_path = os.path.join(output_dir, chain_name)
        if os.path.exists(input_path):
            shutil.copy(input_path, output_path)
            print(f"已复制配置文件到: {output_path}")

def copy_python_scripts():
    py_script_dir = get_path_under_cwd("python_script")
    file_names = [f for f in os.listdir(py_script_dir) if f.endswith(".py")]
    for file_name in file_names:
        input_path = os.path.join(py_script_dir, file_name)
        output_path = get_path_under_onedragon("config", "script_chain", "scripts")
        if not os.path.exists(os.path.join(output_path, file_name)):
            shutil.copy(input_path, output_path)
            print(f"已复制Python脚本{file_name}到: {output_path}")

def config_workflow():
    copy_python_scripts()
    run_config_ui(get_one_dragon_yml_path())
    copy_all_configs()

if __name__ == "__main__":
    config_workflow()
