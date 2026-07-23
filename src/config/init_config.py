import os
import shutil

from src.config.bgi import copy_BGI_User
from src.utils import (
    get_config_yml_path_under_root,
    get_path_under_onedragon,
    get_path_under_root,
    safe_path_join,
)


def copy_python_scripts():
    py_script_dir = get_path_under_root("src", "python_script")
    file_names = [f for f in os.listdir(py_script_dir) if f.endswith(".py")]
    for file_name in file_names:
        input_path = safe_path_join(py_script_dir, file_name)
        output_path = get_path_under_onedragon("config", "script_chain", "scripts")
        if not os.path.exists(safe_path_join(output_path, file_name)):
            shutil.copy(input_path, output_path)
            print(f"已复制Python脚本{file_name}到: {output_path}")
        else:
            print(f"[OneDragonHelper] Python脚本{file_name}已存在，跳过复制")


def need_config_workflow() -> bool:
    """判断是否需要先执行 config_workflow（首次运行时 config.yml 不存在）"""
    return not os.path.exists(get_config_yml_path_under_root())


def config_workflow():
    # 复制 BetterGI 用户配置
    copy_BGI_User()
    # 复制 src/python_scripts 到 OneDragon-ScriptChainer/config/script_chain/scripts
    copy_python_scripts()
    # 从模板生成 config.yml（如果不存在）
    config_path = get_config_yml_path_under_root()
    if not os.path.exists(config_path):
        example_path = safe_path_join(os.path.dirname(config_path), "config.example.yml")
        shutil.copy(example_path, config_path)


if __name__ == "__main__":
    config_workflow()
