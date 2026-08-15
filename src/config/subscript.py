"""
脚本配置读写模块
提供脚本根目录解析、config 路径推导、配置文件读写等功能。
"""

import contextlib
import json
import logging
import os
import re
import urllib.error
import urllib.request

import yaml

from src.utils import (
    get_config_yml_path_under_root,
    get_root_dir,
    require_config_yml_path,
    safe_path_join,
)

logger = logging.getLogger(__name__)

DEFAULT_RUN_TIMEOUT = 3600
"""脚本运行默认超时秒数。当 weekly_timeouts.yml 无条目或不足 7 格时作为 fallback。"""

# ============================================================
# 主配置加载
# ============================================================


def _load_config_yml() -> dict:
    """读取主配置 config.yml"""
    with open(require_config_yml_path(), encoding="utf-8") as f:
        return yaml.safe_load(f)


# ============================================================
# 脚本根目录 & config 路径解析
# ============================================================


def resolve_script_path(path: str) -> str:
    """相对 script_path 解析为基于项目根的绝对路径；绝对路径原样返回。"""
    if _is_absolute_path(path):
        return path
    return safe_path_join(get_root_dir(), path)


def get_process_name(script_path: str) -> str:
    """从 script_path 解析进程名：取 basename 并去后缀（如 ``ok-ww.exe`` → ``ok-ww``）。

    首尾空格先去除（误输入容错），句中空格统一替换为 ``-``
    （如 ``March7th Assistant.exe`` → ``March7th-Assistant``），保证进程名作为
    key 时不含空格（拼接路径 / 命令行传参更安全）。

    先统一为 ``/`` 分隔再取 basename，使 Windows 反斜杠路径（``D:\\game\\ok-ww.exe``）
    在 Linux 的 CI 上也能正确解析（config.example.yml / 用户配置均为 Windows 路径）。

    仅对 exe 脚本有意义（python/bat 等脚本文件无独立进程名）。
    """
    base = os.path.splitext(os.path.basename(script_path.replace("\\", "/")))[0]
    return base.strip().replace(" ", "-")


def _is_exe_script(script_path: str) -> bool:
    """判断脚本路径是否 exe 可执行文件（大小写不敏感）。"""
    return script_path.lower().endswith(".exe")


def get_script_name(script: dict) -> str:
    """脚本唯一标识 script_name（全链路内部标识）。

    - exe 脚本 → 进程名（script_path basename 去后缀，如 ok-ww / BetterGI）
    - python/bat 等脚本文件 → display_name（无独立进程名，靠展示名标识）

    Args:
        script: config.yml 的 script_list 条目（含 display_name / script_path）。
    """
    script_path = script.get("script_path", "")
    if _is_exe_script(script_path):
        return get_process_name(script_path)
    return script.get("display_name", "")


def check_script_name_uniqueness(config_data: dict) -> None:
    """断言 config.yml 中所有脚本唯一标识唯一（进程名或 display_name 冲突属配置错误）。"""
    seen: dict[str, str] = {}
    for script in config_data.get("script_list", []):
        script_name = get_script_name(script)
        if not script_name:
            continue
        display_name = script.get("display_name", script_name)
        if script_name in seen:
            raise AssertionError(
                f"[subscript] 脚本标识重复: {script_name}（{seen[script_name]} 与 {display_name}）"
            )
        seen[script_name] = display_name


def get_script_path(script_name: str) -> str:
    """按脚本唯一标识取 script_path，解析相对路径并校验存在。"""
    config_data = _load_config_yml()
    for script in config_data.get("script_list", []):
        if get_script_name(script) == script_name:
            script_path = script.get("script_path", "")
            assert script_path, (
                f"[set_config] config.yml 中 {script_name} 的 script_path 为空"
            )
            script_path = resolve_script_path(script_path)
            normalized = script_path.replace("\\", "/")
            assert os.path.exists(normalized), f"[set_config] exe 不存在: {normalized}"
            return normalized
    assert False, f"[set_config] config.yml 中找不到脚本: {script_name}"  # noqa: B011  # 故意：config.yml 找不到脚本属编程错误，必须用 assert 表达不该发生


def _get_script_root_dir(script_name: str) -> str:
    """
    从 config.yml 中找到指定脚本的 script_path，取其父目录作为脚本项目根目录。
    复用 get_script_path，确保脚本文件存在。
    """
    return os.path.dirname(get_script_path(script_name))


def _get_script_root_dir_soft(script_name: str) -> str | None:
    """
    从 config.yml 解析脚本根目录，**不校验文件存在**（游戏路径只读查询用）。

    返回 None 表示：config.yml 中无此脚本或 script_path 为空（查询无从谈起）。
    """
    config_data = _load_config_yml()
    for script in config_data.get("script_list", []):
        if get_script_name(script) == script_name:
            script_path = script.get("script_path", "")
            if not script_path:
                return None
            # 与 get_script_path 一致：归一化为正斜杠再取父目录，跨平台（Linux CI）
            return os.path.dirname(resolve_script_path(script_path).replace("\\", "/"))
    return None


def get_config_path(script_name: str, rel_path: str) -> str:
    """
    获取指定脚本的 config 文件绝对路径。
    拼接脚本根目录 + config 相对路径（rel_path 由适配层声明，本模块不感知具体脚本）。
    并确保 config 文件存在。
    """
    root = _get_script_root_dir(script_name)
    config_path = safe_path_join(root, rel_path)
    assert os.path.exists(config_path), f"[set_config] config 文件不存在: {config_path}"
    return config_path


# ============================================================
# config 读写
# ============================================================


def load_template(script_name: str, rel_path: str) -> dict | list:
    """
    加载模板文件（相对 config/ 目录），支持 JSON 和 YAML 格式。
    文件不存在或格式不支持时抛出 AssertionError。
    """
    template_path = safe_path_join(get_root_dir(), "config", rel_path)
    assert os.path.exists(template_path), (
        f"[set_config][{script_name}] 未找到模板文件: {template_path}"
    )
    ext = os.path.splitext(template_path)[1].lower()
    with open(template_path, encoding="utf-8") as f:
        if ext == ".json":
            template = json.load(f)
        elif ext in (".yaml", ".yml"):
            template = yaml.safe_load(f)
        else:
            raise ValueError(f"[set_config][{script_name}] 不支持的模板格式: {ext}")
    return template


def load_config(script_name: str, rel_path: str) -> dict | list:
    """
    读取指定脚本的 config 文件，返回解析后的 dict 或 list。
    支持 .json 和 .yaml/.yml 格式。
    assert 文件存在。
    """
    path = get_config_path(script_name, rel_path)
    assert os.path.exists(path), f"[set_config] config 文件不存在: {path}"
    ext = os.path.splitext(path)[1].lower()
    with open(path, encoding="utf-8") as f:
        if ext == ".json":
            return json.load(f)
        elif ext in (".yaml", ".yml"):
            return yaml.safe_load(f)
        raise ValueError(f"[set_config] 不支持的 config 格式: {ext}")


def load_game_config(script_name: str, rel_path: str) -> dict | None:
    """
    读取指定脚本的游戏路径配置文件，返回解析后的 dict。

    与 load_config 的区别：面向「打开游戏」功能的只读查询，**不 assert 文件存在**。
    文件缺失/根目录解析失败时返回 None，由调用方（GUI）优雅降级。
    """
    root = _get_script_root_dir_soft(script_name)
    if root is None:
        return None
    game_config_path = safe_path_join(root, rel_path)
    if not os.path.exists(game_config_path):
        logger.warning(
            f"[set_config][{script_name}] 游戏路径配置文件不存在: {game_config_path}"
        )
        return None
    ext = os.path.splitext(game_config_path)[1].lower()
    with open(game_config_path, encoding="utf-8") as f:
        if ext == ".json":
            return json.load(f)
        elif ext in (".yaml", ".yml"):
            return yaml.safe_load(f)
        raise ValueError(f"[set_config] 不支持的 config 格式: {ext}")


def save_config(script_name: str, rel_path: str, data: dict | list) -> None:
    """
    将数据写回指定脚本的 config 文件。
    保持原始格式（json / yaml）。
    并确保 config 文件已存在且能被写入。
    """
    path = get_config_path(script_name, rel_path)
    ext = os.path.splitext(path)[1].lower()
    with open(path, "w", encoding="utf-8") as f:
        if ext == ".json":
            json.dump(data, f, ensure_ascii=False, indent=4)
        elif ext in (".yaml", ".yml"):
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)
        else:
            raise ValueError(f"[set_config] 不支持的 config 格式: {ext}")


def _is_absolute_path(p: str) -> bool:
    """跨平台判断路径是否为绝对路径。

    除当前平台的 os.path.isabs 外，额外识别 Windows 风格绝对路径
    （盘符路径 ``C:\\...`` 与 UNC ``\\\\...``）。这样在非 Windows 的 CI
    上不会因为 os.path.isabs 不认盘符路径，而把 ``D:\\games\\x.exe``
    误当成相对路径拼到项目根目录前面。
    """
    if os.path.isabs(p):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", p):
        return True
    return p.startswith("\\\\") or p.startswith("//")


def default_script_entry(display_name, script_type, script_path, script_arguments=""):
    """构造一个 config.yml script_list 条目：核心字段由参数指定，其余用默认值补全。

    Args:
        display_name: 脚本显示名。
        script_type: 脚本类型（python / external）。
        script_path: 脚本路径。
        script_arguments: 启动参数，默认空。

    Returns:
        完整的 script_list 条目 dict（含全部默认字段）。
    """
    return {
        "display_name": display_name,
        "game_label": "",
        "script_type": script_type,
        "script_path": script_path,
        "script_process_name": [],
        "game_process_name": "",
        "launcher_mode": False,
        "check_done": "script_closed",
        "kill_script_after_done": True,
        "kill_game_after_done": False,
        "script_arguments": script_arguments,
        "notify_start": False,
        "notify_done": False,
        "notify_log_interval": 0,
        "attach_direction": "",
        "no_log_timeout_seconds": 0,
        "no_log_max_retries": 3,
        "block": True,
    }


def generate_config_from_example() -> None:
    """从 config.example.yml 复制生成 config/config.yml。

    相对 script_path 保留原样，运行时由 resolve_script_path / get_script_path
    按项目根解析（配置可移植、跨机可用）。
    """
    example_path = safe_path_join(get_root_dir(), "config", "config.example.yml")
    config_path = get_config_yml_path_under_root()
    assert os.path.exists(example_path), f"[subscript] 模板不存在: {example_path}"
    with open(example_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)


# ============================================================
# 网络下载
# ============================================================


def download_file(url: str, out_path: str, timeout: int = 10) -> str | None:
    """下载文件到本地（通用工具，供各脚本拉取远程资源，如背景图）。

    Args:
        url: 下载地址。
        out_path: 输出路径（自动创建父目录）。
        timeout: 网络超时秒数。

    Returns:
        输出路径；下载失败（网络/磁盘）→ None，调用方自行降级。
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp_path = f"{out_path}.part"
    try:  # 网络/磁盘操作，失败可恢复，调用方降级处理
        with (
            urllib.request.urlopen(url, timeout=timeout) as resp,  # noqa: S310
            open(tmp_path, "wb") as f,
        ):
            f.write(resp.read())
        os.replace(tmp_path, out_path)
    except (urllib.error.URLError, OSError) as exc:
        logger.warning(f"[subscript] 下载失败 {url}: {exc}")
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        return None
    logger.info(f"[subscript] 下载完成: {out_path}")
    return out_path
