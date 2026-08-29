import os
import subprocess
import sys
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


def get_schedule_yml_path_under_root() -> str:
    """
    获取根目录下的config/schedule.yml文件路径（运行时生成，含邮件授权码，不追溯git）。

    调度运行参数（shutdown / timed_run / mute / rerun / notify）独立存放于此，
    与 config.yml（脚本链声明）解耦；模板见 config/schedule.example.yml。
    :return: 根目录下的config/schedule.yml文件路径
    """
    return safe_path_join(get_root_dir(), "config", "schedule.yml")


def require_config_yml_path() -> str:
    """
    返回 config.yml 路径，并断言该文件已存在。

    把「config.yml 必须存在」这个不变量收敛到一处：所有**读取/依赖**
    config.yml 已存在的调用方都应走本函数，而不是在每个调用点重复
    `assert os.path.exists(...)`。

    注意：本函数仅在 config.yml 应当已存在时调用。以下场景应使用
    `get_config_yml_path_under_root()`（纯路径，不做存在性断言）：
    - 探测/首次生成（launcher.config_workflow）；
    - 作为写入/生成目标（subscript.generate_config_from_example 首次生成 config.yml）。
    """
    path = get_config_yml_path_under_root()
    assert os.path.exists(path), f"[utils] 未找到 config.yml，无法读取配置: {path}"
    return path


def get_weekly_timeouts_yml_path_under_root() -> str:
    """
    获取根目录下的config/weekly_timeouts.yml文件路径
    :return: 根目录下的config/weekly_timeouts.yml文件路径
    """
    return safe_path_join(get_root_dir(), "config", "weekly_timeouts.yml")


def get_weekly_list_yml_path_under_root() -> str:
    """
    获取根目录下的config/weekly_list.yml文件路径。

    该文件是周常声明配置（静态，进 git）：每脚本支持哪些周常、每种是否需选副本。
    与 weekly_timeouts.yml 同级的周常侧配置文件。

    :return: 根目录下的config/weekly_list.yml文件路径
    """
    return safe_path_join(get_root_dir(), "config", "weekly_list.yml")


def get_weekly_start_yml_path_under_root() -> str:
    """
    获取根目录下的config/weekly_start.yml文件路径。

    该文件持久化各脚本的周常起始日（周几起，{脚本标识: 1~7}），与周常声明
    （weekly_list.yml）、周常超时（weekly_timeouts.yml）平级，三套周常侧配置各自独立。

    :return: 根目录下的config/weekly_start.yml文件路径
    """
    return safe_path_join(get_root_dir(), "config", "weekly_start.yml")


# 项目根覆盖（默认 None = 真实项目根）。仅供测试指定临时配置目录：配置读写方
# 全部经 get_root_dir() 派生路径，故改这一个入口即整体改向，无需逐个 patch。
_root_dir_override: str | None = None


@lru_cache
def get_root_dir() -> str:
    """
    获取项目根目录
    :return: 项目根目录（src/ 的父目录）；冻结（PyInstaller）时为 exe 所在目录
    """
    if _root_dir_override is not None:
        return _root_dir_override
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def set_root_dir(path: str | None) -> None:
    """
    覆盖项目根（测试用），传 None 还原真实项目根。

    config/*.yml、gui_state.json、链输出、日志目录等全部由 get_root_dir() 派生，
    故改此一处即整体改向，测试可指向临时目录而不污染本机配置。
    覆盖值取绝对路径：下游 safe_path_join 以根为信任基准做路径穿越校验。

    :param path: 用作项目根的目录；None 表示还原。
    """
    global _root_dir_override
    _root_dir_override = None if path is None else os.path.abspath(path)
    get_root_dir.cache_clear()


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
    assert target == base_abs or target.startswith(base_abs + os.sep), (
        f"[safe_path_join] 检测到路径穿越注入: base={base_abs} target={target}"
    )
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


def open_in_explorer(path: str) -> None:
    """用系统默认程序打开文件或目录（跨平台）。

    Windows 走 ``os.startfile``；其他平台走 ``xdg-open`` / ``open``。
    非 Windows 环境无图形界面时命令可能失败，由调用方 toast 兜底提示。

    Args:
        path: 待打开的文件或目录路径。
    """
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 系统默认程序打开
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.run([opener, path], check=False)
