import logging
import os

from src.config.bgi import copy_BGI_User
from src.config.subscript import generate_config_from_example
from src.utils import get_config_yml_path_under_root
from src.utils_logger import setup_logging

logger = logging.getLogger(__name__)


def need_config_workflow() -> bool:
    """判断是否需要先执行 config_workflow（首次运行时 config.yml 不存在）"""
    return not os.path.exists(get_config_yml_path_under_root())


def config_workflow():
    # 复制 BetterGI 用户配置
    copy_BGI_User()
    # 从模板生成 config.yml（如果不存在），相对 script_path 解析为绝对路径
    config_path = get_config_yml_path_under_root()
    if not os.path.exists(config_path):
        generate_config_from_example()


if __name__ == "__main__":
    setup_logging()
    config_workflow()
