"""单脚本配置读写（原 src/service/script_service.py，已退化为模块函数）。

承载「单脚本」视角的实现：config.yml 的读写（含脚本条目增删改）、单脚本条目查询
与路径解析。周常运行期参数（weekly.yml 的 weekly_start 段 / weekly.yml 的 weekly_timeouts 段）的读写由
:mod:`src.utils.utils_weekly` 负责，本模块协作调用（如新增脚本时建默认 weekly 条目）。

内部标识统一用**脚本唯一标识 script_name**（exe 脚本为进程名、脚本文件为
display_name），display_name 仅用于展示。config.yml 的读写权统一归本模块；
chain_service 模块仅作运行时委托（其内部 ScheduledRun 经 ``load_config`` 取配置）。
对应 GUI 的 ScriptItem 卡片与配置弹窗（SingleScriptConfigDialog）。

链编排（脚本列表/生成/运行）见 :mod:`src.service.chain_service`。
"""

import logging
import os

from src.config.set_config import get_config_path, init_config
from src.utils import (
    get_config_yml_path_under_root,
    require_config_yml_path,
)
from src.utils.utils_sub_config import (
    check_script_name_uniqueness,
    default_script_entry,
    get_script_name,
    is_exe_script,
    resolve_script_path,
)
from src.utils.utils_weekly import (
    delete_weekly,
    ensure_weekly_entry,
    rename_weekly_in_timeouts,
    save_weekly,
)
from src.utils.utils_yaml import dump_yaml, load_yaml

logger = logging.getLogger(__name__)


def load_config() -> dict:
    """读取 config.yml（断言存在），返回完整 script_list 配置。

    入口处一次性校验每个条目含 display_name/script_path 且脚本唯一标识唯一，
    script_list 内部数据此后可安全用直接访问。
    """
    config_path = require_config_yml_path()
    data = load_yaml(config_path)
    assert isinstance(data, dict) and "script_list" in data, (
        "[utils_config] config.yml 缺少 script_list 字段"
    )
    for s in data["script_list"]:
        assert "display_name" in s, (
            f"[utils_config] script_list 条目缺少 display_name: {s}"
        )
        assert "script_path" in s, (
            f"[utils_config] script_list 条目缺少 script_path: {s}"
        )
    check_script_name_uniqueness(data)
    return data


def save_config(data: dict) -> None:
    """写回 config.yml（生成目标，不要求已存在）。

    Args:
        data: 完整 script_list 配置字典。
    """
    assert isinstance(data, dict) and "script_list" in data, (
        "[utils_config] 待保存的 config 缺少 script_list 字段"
    )
    config_path = get_config_yml_path_under_root()
    dump_yaml(config_path, data)


def add_script(script_data: dict) -> None:
    """向 config.yml 的 script_list 追加一个脚本条目，并自动创建 weekly 默认条目。

    脚本唯一标识（get_script_name）不得与已有条目重复（数据完整性约束）。

    Args:
        script_data: 完整脚本条目 dict（含 display_name / script_path 等）。
    """
    assert "display_name" in script_data, "[utils_config] script_data 缺少 display_name"
    assert "script_path" in script_data, "[utils_config] script_data 缺少 script_path"
    config = load_config()
    scripts = config.setdefault("script_list", [])
    new_script_name = get_script_name(script_data)
    assert all(get_script_name(s) != new_script_name for s in scripts), (
        f"[utils_config] 脚本标识已存在: {new_script_name}"
    )
    scripts.append(script_data)
    save_config(config)
    ensure_weekly_entry(new_script_name)
    init_config(new_script_name)


def remove_script(script_name: str) -> None:
    """从 config.yml 的 script_list 移除指定脚本条目，并自动清理 weekly 孤儿。

    Args:
        script_name: 要移除的脚本唯一标识。
    """
    config = load_config()
    scripts = config.setdefault("script_list", [])
    target = next(
        (s for s in scripts if get_script_name(s) == script_name),
        None,
    )
    assert target is not None, f"[utils_config] 找不到脚本: {script_name}"
    scripts.remove(target)
    save_config(config)
    delete_weekly(script_name)


def update_script(
    old_script_name: str,
    new_display_name: str,
    config_patch: dict,
    weekly_timeouts: list[int | None],
) -> str:
    """更新单个脚本条目字段并同步 weekly_timeouts。

    以脚本唯一标识定位条目；自动处理标识变更（含 weekly 迁移）与
    kill_game_after_done 自洽（未设置 game_process_name 时强制 False）。

    Args:
        old_script_name: 原脚本唯一标识（用于定位条目）。
        new_display_name: 新 display_name（展示名，可保留原名）。
        config_patch: 要写入条目顶层字段的映射（如 script_path/check_done）。
        weekly_timeouts: 7 格超时输入值，空输入为 None（落盘前转默认超时）。

    Returns:
        落盘后的脚本唯一标识（标识可能因 script_path/display_name 变更而改变），
        供调用方在落盘后触发依赖新路径的后续动作（如游戏侧周几起同步）。
    """
    assert new_display_name, "[utils_config] 脚本名称不能为空"
    config = load_config()
    target = None
    for script in config.setdefault("script_list", []):
        if get_script_name(script) == old_script_name:
            target = script
            break
    assert target is not None, f"[utils_config] 找不到脚本: {old_script_name}"

    for key, value in config_patch.items():
        target[key] = value
    target["display_name"] = new_display_name

    new_script_name = get_script_name(target)
    if new_script_name != old_script_name:
        assert all(
            get_script_name(s) != new_script_name
            for s in config["script_list"]
            if s is not target
        ), f"[utils_config] 脚本标识已存在: {new_script_name}"

    # 配置自洽：未设置游戏进程名时「运行后关闭游戏」强制 False
    if not target.get("game_process_name", ""):
        target["kill_game_after_done"] = False

    save_config(config)

    if new_script_name != old_script_name:
        rename_weekly_in_timeouts(old_script_name, new_script_name)
    save_weekly(new_script_name, weekly_timeouts)
    init_config(new_script_name)
    return new_script_name


def get_script(script_name: str) -> dict | None:
    """按脚本唯一标识读取单个脚本条目。

    Args:
        script_name: 脚本唯一标识（exe 用进程名，脚本文件用 display_name）。

    Returns:
        脚本条目 dict；不存在时返回 None。
    """
    config = load_config()
    for script in config.get("script_list", []):
        if get_script_name(script) == script_name:
            return script
    return None


def build_script_entry(file_path: str, existing_script_names: set[str]) -> dict:
    """按文件路径构造脚本条目：去重命名 + 类型推断 + 默认字段补全。

    新脚本的 display_name 与唯一标识一致（exe 为进程名，脚本文件为 display_name），
    去重基于唯一标识。

    Args:
        file_path: 选中的脚本文件路径（已规范化）。
        existing_script_names: 已有脚本唯一标识集合，用于去重命名。

    Returns:
        完整的 script_list 条目 dict（display_name 不与 existing 重复）。
    """
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    display_name = base_name
    suffix = 1
    while display_name in existing_script_names:
        display_name = f"{base_name}_{suffix}"
        suffix += 1

    script_type = "python" if file_path.lower().endswith(".py") else "external"
    return default_script_entry(
        display_name=display_name,
        script_type=script_type,
        script_path=file_path,
    )


def config_file_path(script_name: str) -> tuple[str | None, str | None]:
    """返回该脚本「配置文件」的本地路径（用于外部打开）与失败原因。

    python 脚本返回其 .py 源文件路径；external 脚本返回其内部 config 路径。
    文件不存在或脚本未适配配置文件时返回 (None, error)，error 可直接展示给用户。

    Args:
        script_name: 脚本唯一标识。

    Returns:
        (path, error)：path 为可打开的配置文件路径（str）；error 为非空字符串时
            表示未适配或文件缺失（可直接展示），此时 path 为 None。
    """
    script = get_script(script_name)
    if script is None:
        return None, f"找不到脚本: {script_name}"
    script_type = script.get("script_type", "external")
    script_path = script.get("script_path", "")
    if script_type == "python":
        resolved = resolve_script_path(script_path)
        if not resolved or not os.path.isfile(resolved):
            return (
                None,
                f"找不到脚本文件：{script_path or '(未设置路径)'}",
            )
        return resolved, None
    if is_exe_script(script_path):
        try:
            config_path = get_config_path(get_script_name(script))
        except AssertionError as e:
            return None, f"该脚本暂未适配配置文件，无法打开：{e}"
        if not os.path.isfile(config_path):
            return None, f"配置文件不存在：{config_path}"
        return config_path, None
    # external 但非 exe（如 bat 等）：无 config 适配，打开其自身
    resolved = resolve_script_path(script_path)
    if not resolved or not os.path.isfile(resolved):
        return None, f"找不到脚本文件：{script_path or '(未设置路径)'}"
    return resolved, None
