import os
import shutil

try:
    from utils import get_path_under_root, get_onedragon_yml_path_under_root, get_path_under_onedragon
    from config.onedragon_config_ui import run_config_ui
except ImportError:
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from utils import get_path_under_root, get_onedragon_yml_path_under_root, get_path_under_onedragon
    from config.onedragon_config_ui import run_config_ui

def copy_python_scripts():
    py_script_dir = get_path_under_root("python_script")
    file_names = [f for f in os.listdir(py_script_dir) if f.endswith(".py")]
    for file_name in file_names:
        input_path = os.path.join(py_script_dir, file_name)
        output_path = get_path_under_onedragon("config", "script_chain", "scripts")
        if not os.path.exists(os.path.join(output_path, file_name)):
            shutil.copy(input_path, output_path)
            print(f"已复制Python脚本{file_name}到: {output_path}")

def config_workflow():
    copy_python_scripts()
    run_config_ui(get_onedragon_yml_path_under_root())

if __name__ == "__main__":
    config_workflow()
