import os
import sys
import shutil
import yaml

# Allow direct execution by adding parent directory to sys.path if utils is not directly importable
try:
    import utils
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils import get_our_bgi_user_dir, get_onedragon_yml_path_under_root

def get_BGI_user_dir():
    """
    获取BetterGI配置文件中的脚本路径
    :return: 包含脚本路径
    """
    with open(get_onedragon_yml_path_under_root(), 'r', encoding='utf-8') as f:
        config_data = yaml.safe_load(f)
        script_list = config_data.get('script_list', [])
        for script in script_list:
            if script.get('display_name') == '原神':
                BGI_dir = os.path.dirname(script.get('script_path'))
                return os.path.join(BGI_dir, 'User')
    return None

def copy_BGI_config():
    """
    复制BetterGI配置到指定路径
    :return: None
    """
    user_dir = get_BGI_user_dir()
    if user_dir:
        shutil.copytree(get_our_bgi_user_dir(), user_dir, dirs_exist_ok=True)

if __name__ == "__main__":
    copy_BGI_config()
    print("配置复制完成")
       