"""源码应用安装服务。"""

import json
import os
import re
import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path

from source_app_manager import Application, install, launch_command

from src.utils import get_path_under_root
from src.utils.utils_io import load_data
from src.utils.utils_job import InvalidJob


def install_source_application(
    application_id: str,
    repository: str,
    revision: str,
    python_version: str,
    requirements: str,
    directory: str,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """在指定目录安装源码应用，返回应用源码目录。"""
    if not isinstance(application_id, str) or not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9_-]*", application_id
    ):
        raise InvalidJob("源码应用标识无效")
    values = (repository, revision, python_version, requirements, directory)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise InvalidJob("源码应用安装参数不能为空")
    root = Path(directory).expanduser()
    if not root.is_absolute():
        raise InvalidJob("源码应用目录必须是绝对路径")
    target = root / application_id
    app = Application(repository, revision, python_version, requirements)
    try:
        source = install(app, target, progress=progress)
    except FileExistsError:
        # 安装已完成但注册失败时，允许对同一版本重试注册。
        state_path = target / "install.json"
        if not state_path.is_file():
            raise
        state = json.loads(state_path.read_text(encoding="utf-8"))
        expected = {
            "repository": repository,
            "revision": revision,
            "python_version": python_version,
            "requirements": requirements,
        }
        if state.get("complete") is not True or state.get("application") != expected:
            raise
        source = target / "app"
        executable = (
            source
            / ".venv"
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        if not source.is_dir() or not executable.is_file():
            raise
    return {"application_id": application_id, "source": str(source)}


def source_catalog() -> dict:
    """读取随助手发布的源码应用声明。"""
    path = get_path_under_root("config", "source_applications.yml")
    data = load_data(path, file_format="yaml")
    assert isinstance(data, dict) and data.get("version", 0) == 1
    assert "applications" in data and isinstance(data["applications"], dict)
    return data["applications"]


def install_catalog_application(
    application_id: str,
    directory: str,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """安装声明中的最新稳定版本。"""
    catalog = source_catalog()
    if not isinstance(application_id, str) or application_id not in catalog:
        raise InvalidJob("未知源码应用")
    assert application_id in catalog
    definition = catalog[application_id]
    assert isinstance(definition, dict)
    for key in ("repository", "release_api", "python_version", "requirements"):
        assert key in definition and isinstance(definition[key], str)
    if not isinstance(directory, str) or not Path(directory).is_absolute():
        raise InvalidJob("源码应用目录必须是绝对路径")
    if (
        definition.get("ascii_path", False)
        and not str(Path(directory) / application_id).isascii()
    ):
        raise InvalidJob("此应用的安装目录须使用英文路径")
    from src.utils import utils_config
    from src.utils.utils_sub_config import get_script_name

    config = utils_config.load_config()
    assert "script_list" in config
    if any(get_script_name(item) == application_id for item in config["script_list"]):
        raise InvalidJob(
            f"脚本标识已存在: {application_id}；请先从助手移除已有同标识脚本"
        )
    if progress is not None:
        progress("正在检查最新版本")
    import requests

    response = requests.get(definition["release_api"], timeout=30)
    response.raise_for_status()
    release = response.json()
    if (
        not isinstance(release, dict)
        or not isinstance(release.get("tag_name", ""), str)
        or not release.get("tag_name", "")
    ):
        raise InvalidJob("上游最新版本信息无效")
    assert "tag_name" in release
    return install_source_application(
        application_id,
        definition["repository"],
        release["tag_name"],
        definition["python_version"],
        definition["requirements"],
        directory,
        progress=progress,
    )


def format_arguments(arguments: list[str]) -> str:
    """将参数列表格式化为当前平台的命令行文本。"""
    return (
        subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)
    )


def parse_arguments(value: str) -> list[str]:
    """按当前平台的命令行规则解析参数，不调用 shell。"""
    if not value:
        return []
    if os.name != "nt":
        return shlex.split(value)
    import ctypes
    from ctypes import wintypes

    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    result = shell.CommandLineToArgvW("program " + value, ctypes.byref(count))
    if not result:
        raise OSError(ctypes.get_last_error(), "无法解析启动参数")
    try:
        return [result[index] for index in range(1, count.value)]
    finally:
        kernel.LocalFree(result)


def source_launch_command(script: dict, arguments: list[str]):
    """解析已安装源码应用的解释器、入口与工作目录。"""
    assert "source_root" in script and "script_path" in script
    if not isinstance(arguments, list) or not all(
        isinstance(argument, str) for argument in arguments
    ):
        raise InvalidJob("源码应用参数必须为文本列表")
    if not isinstance(script["source_root"], str) or not isinstance(
        script["script_path"], str
    ):
        raise InvalidJob("源码目录和入口必须为文本")
    root = Path(script["source_root"]).resolve()
    entry = Path(script["script_path"]).resolve()
    try:
        relative = entry.relative_to(root)
    except ValueError as exc:
        raise InvalidJob("Python 入口须位于源码目录内") from exc
    return launch_command(root, str(relative), arguments)


def register_source_application(
    application_id: str,
    display_name: str,
    source_root: str,
    script_path: str,
    manual_arguments: list[str],
    run_arguments: list[str],
    replace_existing: bool = False,
) -> dict:
    """将已安装源码应用注册到助手。"""
    from src.utils import utils_config, utils_weekly
    from src.utils.utils_sub_config import default_script_entry, get_script_name

    if not isinstance(application_id, str) or not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9_-]*", application_id
    ):
        raise InvalidJob("源码应用标识无效")
    if not isinstance(display_name, str) or not display_name.strip():
        raise InvalidJob("源码应用名称不能为空")
    if type(replace_existing) is not bool:
        raise InvalidJob("替换选项必须是布尔值")
    if not isinstance(source_root, str) or not Path(source_root).is_absolute():
        raise InvalidJob("源码目录必须是绝对路径")
    if not isinstance(script_path, str) or not Path(script_path).is_absolute():
        raise InvalidJob("Python 入口必须是绝对路径")
    if not all(
        isinstance(args, list) and all(isinstance(arg, str) for arg in args)
        for args in (manual_arguments, run_arguments)
    ):
        raise InvalidJob("源码应用参数必须为文本列表")
    entry = default_script_entry(display_name.strip(), "external", script_path)
    entry.update(
        script_id=application_id,
        source_root=source_root,
        source_manual_arguments=manual_arguments,
        source_arguments=run_arguments,
        script_arguments=format_arguments(run_arguments),
    )
    try:
        source_launch_command(entry, manual_arguments)
        source_launch_command(entry, run_arguments)
    except (OSError, ValueError, RuntimeError) as exc:
        raise InvalidJob(f"源码应用无效: {exc}") from exc
    config = utils_config.load_config()
    assert "script_list" in config
    existing = next(
        (
            index
            for index, item in enumerate(config["script_list"])
            if get_script_name(item) == application_id
        ),
        None,
    )
    if existing is None:
        config["script_list"].append(entry)
    elif replace_existing:
        config["script_list"][existing] = entry
    else:
        raise InvalidJob(f"脚本标识已存在: {application_id}")
    utils_config.save_config(config)
    utils_weekly.ensure_weekly_entry(application_id)
    return {"script_name": application_id, "display_name": display_name.strip()}


def configure_source_application(
    script_name: str,
    script_path: str,
    manual_arguments: list[str],
    run_arguments: list[str],
) -> dict:
    """保存源码应用的入口与两种启动参数。"""
    from src.config.set_config import invalidate_config
    from src.utils import utils_config
    from src.utils.utils_sub_config import get_script_name

    if not isinstance(script_name, str) or not script_name:
        raise InvalidJob("脚本标识无效")
    if not isinstance(script_path, str) or not Path(script_path).is_absolute():
        raise InvalidJob("Python 入口必须是绝对路径")
    config = utils_config.load_config()
    assert "script_list" in config
    entry = next(
        (
            item
            for item in config["script_list"]
            if get_script_name(item) == script_name
        ),
        None,
    )
    if entry is None or "source_root" not in entry:
        raise InvalidJob("源码应用不存在")
    if not all(
        isinstance(args, list) and all(isinstance(arg, str) for arg in args)
        for args in (manual_arguments, run_arguments)
    ):
        raise InvalidJob("源码应用参数必须为文本列表")
    candidate = {
        **entry,
        "script_path": script_path,
        "source_manual_arguments": manual_arguments,
        "source_arguments": run_arguments,
        "script_arguments": format_arguments(run_arguments),
    }
    try:
        source_launch_command(candidate, manual_arguments)
        source_launch_command(candidate, run_arguments)
    except (OSError, ValueError, RuntimeError) as exc:
        raise InvalidJob(f"源码应用无效: {exc}") from exc
    entry.update(candidate)
    utils_config.save_config(config)
    invalidate_config(script_name)
    return {"script_name": script_name}


class SourceAppService:
    """源码应用入口；安装任务与其他后台任务共用执行器。"""

    def __init__(self, jobs):
        self._jobs = jobs

    def start_install(
        self,
        application_id,
        repository,
        revision,
        python_version,
        requirements,
        directory,
    ) -> dict:
        return self._jobs.start(
            "source_install",
            lambda: install_source_application(
                application_id,
                repository,
                revision,
                python_version,
                requirements,
                directory,
                progress=self._jobs.message,
            ),
        )

    def start_catalog_install(self, application_id, directory) -> dict:
        return self._jobs.start(
            "source_install",
            lambda: install_catalog_application(
                application_id,
                directory,
                progress=self._jobs.message,
            ),
        )

    catalog = staticmethod(source_catalog)
    register = staticmethod(register_source_application)
    configure = staticmethod(configure_source_application)
