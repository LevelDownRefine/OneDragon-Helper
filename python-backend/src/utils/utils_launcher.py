"""Windows 游戏启动辅助：校验官方启动器并设置游戏的父进程。"""

import ctypes
import json
import logging
import math
import os
import subprocess
import sys
import time
from collections.abc import Collection
from ctypes import wintypes
from typing import TypedDict

import psutil

logger = logging.getLogger(__name__)

ENDFIELD_TRUSTED_SIGNERS = frozenset(
    {
        "2B366F397E64A9494A553B70004E8CA1AAE02B9D",
        "FF4AF264C36A27F0C805936708EF8EC67B396225",
    }
)
ENDFIELD_PARENT_PROCESS = "Games.exe"
ENDFIELD_GAME_PROCESS = "Endfield.exe"
_PARENT_PROCESS_ATTRIBUTE = 0x00020000
_PROCESS_CREATE_PROCESS = 0x0080
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000


class GameLaunchInfo(TypedDict):
    launcher_path: str
    game_path: str
    launcher_process_name: str
    game_process_name: str
    trusted_signers: frozenset[str]


def get_installed_launcher(
    script_name: str, uninstall_id: str, filename: str
) -> str | None:
    """从 Windows 卸载记录定位启动器；记录或文件缺失时返回 None。"""
    if sys.platform != "win32":
        return None
    import winreg

    key_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{uninstall_id}"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ | view) as key:
                    folder, _ = winreg.QueryValueEx(key, "InstallLocation")
            except OSError as error:
                logger.debug(
                    "[%s] 读取启动器安装记录失败 (%s): %s",
                    script_name,
                    type(error).__name__,
                    error,
                )
                continue
            if not isinstance(folder, str) or not os.path.isabs(folder):
                logger.warning("[%s] 启动器安装目录无效: %r", script_name, folder)
                continue
            launcher = os.path.join(folder, filename)
            if os.path.isfile(launcher):
                return os.path.abspath(launcher)
    return None


def get_endfield_launch_info(launcher_path: str, game_path: str) -> GameLaunchInfo:
    """构造终末地官方启动器流程所需信息。"""
    return {
        "launcher_path": launcher_path,
        "game_path": game_path,
        "launcher_process_name": ENDFIELD_PARENT_PROCESS,
        "game_process_name": ENDFIELD_GAME_PROCESS,
        "trusted_signers": ENDFIELD_TRUSTED_SIGNERS,
    }


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", wintypes.LPVOID)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _check_win32(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def _kernel32():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "OpenProcess": (
            [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
            wintypes.HANDLE,
        ),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "QueryFullProcessImageNameW": (
            [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ],
            wintypes.BOOL,
        ),
        "InitializeProcThreadAttributeList": (
            [
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.POINTER(ctypes.c_size_t),
            ],
            wintypes.BOOL,
        ),
        "UpdateProcThreadAttribute": (
            [
                wintypes.LPVOID,
                wintypes.DWORD,
                ctypes.c_size_t,
                wintypes.LPVOID,
                ctypes.c_size_t,
                wintypes.LPVOID,
                wintypes.LPVOID,
            ],
            wintypes.BOOL,
        ),
        "DeleteProcThreadAttributeList": ([wintypes.LPVOID], None),
        "CreateProcessW": (
            [
                wintypes.LPCWSTR,
                wintypes.LPWSTR,
                wintypes.LPVOID,
                wintypes.LPVOID,
                wintypes.BOOL,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.LPCWSTR,
                ctypes.POINTER(_StartupInfoEx),
                ctypes.POINTER(_ProcessInfo),
            ],
            wintypes.BOOL,
        ),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes = arguments
        function.restype = result
    return kernel


def _verify_official_launcher(path: str, trusted_signers: Collection[str]) -> None:
    """Check the Authenticode status and allowlisted Hypergryph signer."""
    system_root = os.environ.get("SYSTEMROOT")
    if not system_root:
        raise OSError("无法确定 Windows 系统目录")
    powershell = os.path.join(
        system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
    )
    script = (
        "$ErrorActionPreference='Stop'; "
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
        "$s=Get-AuthenticodeSignature -LiteralPath $env:ODH_VERIFY_LAUNCHER; "
        "@{status=[int]$s.Status; signer=$s.SignerCertificate.Thumbprint} | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        env={
            **os.environ,
            "ODH_VERIFY_LAUNCHER": path,
            "PSModulePath": os.path.join(
                system_root, "System32", "WindowsPowerShell", "v1.0", "Modules"
            ),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    signature = json.loads(result.stdout)
    signer = (signature.get("signer") or "").upper()
    allowed_signers = {thumbprint.upper() for thumbprint in trusted_signers}
    if signature.get("status") != 0 or signer not in allowed_signers:
        raise RuntimeError(f"启动器签名无效或不受信任：{path}")


def _running_pids(name: str) -> list[int]:
    pids = []
    for process in psutil.process_iter(["name"]):
        try:
            if (process.info["name"] or "").casefold() == name.casefold():
                pids.append(process.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def _verified_parent(kernel, name: str, trusted_signers: Collection[str]) -> int | None:
    for pid in _running_pids(name):
        handle = None
        try:
            handle = _check_win32(
                kernel.OpenProcess(
                    _PROCESS_CREATE_PROCESS | _PROCESS_QUERY_LIMITED_INFORMATION,
                    False,
                    pid,
                )
            )
            image = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(image))
            _check_win32(
                kernel.QueryFullProcessImageNameW(
                    handle, 0, image, ctypes.byref(length)
                )
            )
            if os.path.basename(image.value).casefold() != name.casefold():
                raise RuntimeError(f"启动器进程路径无效：{image.value}")
            _verify_official_launcher(image.value, trusted_signers)
            logger.info("已验证官方启动器进程：pid=%s, path=%s", pid, image.value)
            return handle
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
            if handle:
                kernel.CloseHandle(handle)
            logger.warning("无法使用启动器进程 PID %s：%s", pid, error)
    return None


def _prepare_parent(
    kernel,
    launcher_path: str,
    launcher_arguments: str,
    launcher_process_name: str,
    trusted_signers: Collection[str],
    timeout: float,
) -> int:
    parent = _verified_parent(kernel, launcher_process_name, trusted_signers)
    if parent:
        return parent
    _verify_official_launcher(launcher_path, trusted_signers)
    command_line = subprocess.list2cmdline([launcher_path])
    if launcher_arguments:
        command_line += " " + launcher_arguments
    subprocess.Popen(
        command_line,
        executable=launcher_path,
        cwd=os.path.dirname(launcher_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        parent = _verified_parent(kernel, launcher_process_name, trusted_signers)
        if parent:
            return parent
        time.sleep(0.25)
    raise TimeoutError(f"官方启动器在 {timeout:g} 秒内未就绪")


def _create_game_process(kernel, game_path: str, arguments: str, parent: int) -> int:
    size = ctypes.c_size_t()
    kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    if not size.value:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(size.value)
    attributes = ctypes.cast(buffer, wintypes.LPVOID)
    _check_win32(
        kernel.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size))
    )
    try:
        parent_handle = wintypes.HANDLE(parent)
        _check_win32(
            kernel.UpdateProcThreadAttribute(
                attributes,
                0,
                _PARENT_PROCESS_ATTRIBUTE,
                ctypes.byref(parent_handle),
                ctypes.sizeof(parent_handle),
                None,
                None,
            )
        )
        startup = _StartupInfoEx()
        startup.StartupInfo.cb = ctypes.sizeof(startup)
        startup.lpAttributeList = attributes
        process = _ProcessInfo()
        command = ctypes.create_unicode_buffer(
            (subprocess.list2cmdline([game_path]) + " " + arguments).strip()
        )
        _check_win32(
            kernel.CreateProcessW(
                game_path,
                command,
                None,
                None,
                False,
                _EXTENDED_STARTUPINFO_PRESENT | subprocess.CREATE_NO_WINDOW,
                None,
                os.path.dirname(game_path),
                ctypes.byref(startup),
                ctypes.byref(process),
            )
        )
        try:
            return process.dwProcessId
        finally:
            try:
                kernel.CloseHandle(process.hThread)
            finally:
                kernel.CloseHandle(process.hProcess)
    finally:
        kernel.DeleteProcThreadAttributeList(attributes)


def launch_game(
    game_path: str,
    launcher_path: str,
    launcher_arguments: str,
    launcher_process_name: str,
    game_process_name: str,
    trusted_signers: Collection[str],
    timeout: float = 30,
) -> int | None:
    """Launch a game under a signature-verified process from its official launcher."""
    if sys.platform != "win32":
        raise OSError("通过父进程启动游戏仅支持 Windows")
    if not os.path.isfile(game_path):
        raise FileNotFoundError(f"未找到游戏程序：{game_path}")
    if not os.path.isfile(launcher_path):
        raise FileNotFoundError(f"未找到官方启动器：{launcher_path}")
    if not isinstance(launcher_arguments, str):
        raise ValueError("游戏启动参数无效")
    if not isinstance(launcher_process_name, str) or not launcher_process_name:
        raise ValueError("启动器进程名无效")
    if not isinstance(game_process_name, str) or not game_process_name:
        raise ValueError("游戏进程名无效")
    if (
        isinstance(trusted_signers, str)
        or not isinstance(trusted_signers, Collection)
        or not trusted_signers
        or not all(isinstance(signer, str) and signer for signer in trusted_signers)
    ):
        raise ValueError("未配置受信任的启动器签名")
    if (
        not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("等待启动器的超时时间必须大于零")
    if _running_pids(game_process_name):
        logger.info("%s 已经运行，跳过重复启动", game_process_name)
        return None

    kernel = _kernel32()
    parent = _prepare_parent(
        kernel,
        os.path.abspath(launcher_path),
        launcher_arguments,
        launcher_process_name,
        trusted_signers,
        timeout,
    )
    try:
        if _running_pids(game_process_name):
            logger.info("%s 已在启动器就绪期间启动，跳过重复启动", game_process_name)
            return None
        pid = _create_game_process(kernel, os.path.abspath(game_path), "", parent)
        logger.info("已通过官方启动器进程创建 %s：pid=%s", game_process_name, pid)
        return pid
    finally:
        kernel.CloseHandle(parent)
