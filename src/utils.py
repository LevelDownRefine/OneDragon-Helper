import os
from functools import lru_cache


def get_our_bgi_user_dir() -> str:
    """
    获取当前工作目录下的config/BGI_User目录
    :return: 当前工作目录下的config/BGI_User目录
    """
    return safe_path_join(get_root_dir(), "config", "BGI_User")

def get_config_yml_path_under_root() -> str:
    """
    获取根目录下的config/config.yml文件路径（运行时生成，含个人信息，不追溯git）
    :return: 根目录下的config/config.yml文件路径
    """
    return safe_path_join(get_root_dir(), "config", "config.yml")

def get_weekly_timeouts_yml_path_under_root() -> str:
    """
    获取根目录下的config/weekly_timeouts.yml文件路径
    :return: 根目录下的config/weekly_timeouts.yml文件路径
    """
    return safe_path_join(get_root_dir(), "config", "weekly_timeouts.yml")

def get_path_under_onedragon(*subs) -> str:
    """
    获取工作目录下的路径
    :param subs: 子目录路径 可以传入多个表示多级
    :return: 工作目录下的路径
    """
    return join_dir_path_with_mk(get_root_dir(), "OneDragon-ScriptChainer", *subs)

@lru_cache
def get_root_dir() -> str:
    """
    获取项目根目录
    :return: 项目根目录（src/ 的父目录）
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_path_under_root(*subs) -> str:
    """
    获取当前工作目录下的路径
    :param subs: 子目录路径 可以传入多个表示多级
    :return: 当前工作目录下的路径
    """
    return join_dir_path_with_mk(get_root_dir(), *subs)

def safe_path_join(base: str, *paths: str) -> str:
    """
    安全地将 base 与若干子路径拼接，防止路径穿越注入。

    子路径可能来自外部输入（config.yml、模板映射等），若含有 `..`、
    绝对路径或（Windows）盘符，普通 os.path.join 会逃逸到 base 之外。
    本函数对拼接结果做规范化后校验：结果必须仍位于 base 目录内，
    否则视为注入攻击，assert 失败。

    :param base: 基准目录（信任根）
    :param paths: 待拼接的子路径片段（可能不可信）
    :return: 规范化后的绝对路径，保证等于 base 或位于 base 之内
    """
    base_abs = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base_abs, *paths))
    # startswith 判断可同时拦截 `..` 逃逸、绝对路径覆盖、跨盘符（Windows）
    assert target == base_abs or target.startswith(base_abs + os.sep), \
        f"[safe_path_join] 检测到路径穿越注入: base={base_abs} target={target}"
    return target


def join_dir_path_with_mk(base: str, *subs) -> str:
    """
    在 base 下逐级拼接子目录并创建（不存在则 mkdir）。
    使用 safe_path_join 保证拼接不逃逸 base（防路径穿越注入）。
    :param base: 基准目录（信任根）
    :param subs: 子目录名，可传入多个表示多级；为 None 的段会被跳过
    :return: 拼接并创建后的目录绝对路径
    """
    parts = [sub for sub in subs if sub is not None]
    target = safe_path_join(base, *parts)  # 整体校验不逃逸 base
    acc = os.path.abspath(base)
    for sub in parts:
        acc = os.path.join(acc, sub)
        if not os.path.exists(acc):
            os.mkdir(acc)
    return target
