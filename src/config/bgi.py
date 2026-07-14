import os
import shutil
import yaml

from src.utils import get_our_bgi_user_dir, get_config_yml_path_under_root

def get_BGI_user_dir():
    """
    获取BetterGI配置文件中的脚本路径
    :return: 包含脚本路径
    """
    with open(get_config_yml_path_under_root(), 'r', encoding='utf-8') as f:
        config_data = yaml.safe_load(f)
        script_list = config_data.get('script_list', [])
        for script in script_list:
            if script.get('display_name') == '原神':
                BGI_dir = os.path.dirname(script.get('script_path'))
                return os.path.join(BGI_dir, 'User')
    return None

def copy_BGI_User():
    """
    复制BetterGI配置到指定路径
    :return: None
    """
    user_dir = get_BGI_user_dir()
    assert user_dir, "未找到BetterGI用户目录"
    print(f"[BetterGI] 复制BetterGI配置到: {user_dir}")
    shutil.copytree(get_our_bgi_user_dir(), user_dir, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("OneDragon"))

if __name__ == "__main__":
    copy_BGI_User()
    print("配置复制完成")
       