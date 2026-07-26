import logging
import os
import shutil

from src.config.bgi import copy_BGI_User
from src.utils import (
    get_config_yml_path_under_root,
    safe_path_join,
)
from src.utils_logger import setup_logging

logger = logging.getLogger(__name__)


def need_config_workflow() -> bool:
    """判断是否需要先执行 config_workflow（首次运行时 config.yml 不存在）"""
    return not os.path.exists(get_config_yml_path_under_root())


def config_workflow():
    # 复制 BetterGI 用户配置
    copy_BGI_User()
    # 从模板生成 config.yml（如果不存在）
    config_path = get_config_yml_path_under_root()
    if not os.path.exists(config_path):
        example_path = safe_path_join(os.path.dirname(config_path), "config.example.yml")
        shutil.copy(example_path, config_path)


if __name__ == "__main__":
    setup_logging()
    config_workflow()
