import logging
import os
import shutil

from src.config.subscript import get_process_name, resolve_script_path
from src.config.yaml_rt import load_yaml
from src.utils import (
    get_our_bgi_user_dir,
    require_config_yml_path,
    safe_path_join,
)
from src.utils_logger import setup_logging

logger = logging.getLogger(__name__)


def get_BGI_user_dir():
    """返回 BetterGI 配置目录（原神 exe 父目录下的 User）。"""
    with open(require_config_yml_path(), encoding="utf-8") as f:
        config_data = load_yaml(f)
        script_list = config_data.get("script_list", [])
        for script in script_list:
            if get_process_name(script.get("script_path", "")) == "BetterGI":
                path = script.get("script_path")
                if not path:
                    continue
                return safe_path_join(
                    os.path.dirname(resolve_script_path(path)), "User"
                )
    return None


def copy_BGI_User():
    """
    复制BetterGI配置到指定路径
    :return: None
    """
    user_dir = get_BGI_user_dir()
    assert user_dir, "未找到BetterGI用户目录"
    logger.info(f"[BetterGI] 复制BetterGI配置到: {user_dir}")
    shutil.copytree(get_our_bgi_user_dir(), user_dir, dirs_exist_ok=True)


if __name__ == "__main__":
    setup_logging()
    copy_BGI_User()
    logger.info("配置复制完成")
