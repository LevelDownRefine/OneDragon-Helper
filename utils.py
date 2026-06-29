import os

BaseDIR = os.path.dirname(os.path.abspath(__file__))
OneDragonScriptChainerDir = os.path.join(BaseDIR, "OneDragon-ScriptChainer")
OurBGIUserDir = os.path.join(BaseDIR, "BGI_User")

def get_onedragon_yml_path_under_root() -> str:
    """
    获取根目录下的config.yml文件路径
    :return: 根目录下的config.yml文件路径
    """
    return os.path.join(BaseDIR, "config.yml")

def get_script_chain_under_onedragon() -> str:
    """
    获取OneDragon-ScriptChainer目录下的配置文件路径
    :return: OneDragon-ScriptChainer目录下的配置文件路径
    """
    return get_path_under_onedragon("config", "script_chain")

def get_path_under_onedragon(*subs) -> str:
    """
    获取工作目录下的路径
    :param subs: 子目录路径 可以传入多个表示多级
    :return: 工作目录下的路径
    """
    return join_dir_path_with_mk(OneDragonScriptChainerDir, *subs)

def get_root_dir() -> str:
    """
    获取当前工作目录
    :return: 当前工作目录
    """
    return os.path.dirname(os.path.abspath(__file__))

def get_path_under_root(*subs) -> str:
    """
    获取当前工作目录下的路径
    :param subs: 子目录路径 可以传入多个表示多级
    :return: 当前工作目录下的路径
    """
    return join_dir_path_with_mk(get_root_dir(), *subs)

def join_dir_path_with_mk(path: str, *subs) -> str:
    """
    拼接目录路径和子目录
    如果拼接后的目录不存在 则创建
    :param path: 目录路径
    :param subs: 子目录路径 可以传入多个表示多级
    :return: 拼接后的子目录路径
    """
    target_path = path
    for sub in subs:
        if sub is None:
            continue
        target_path = os.path.join(target_path, sub)
        if not os.path.exists(target_path):
            os.mkdir(target_path)
    return target_path
