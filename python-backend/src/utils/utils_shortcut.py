"""读取 Windows 快捷方式的启动信息，不修改快捷方式。"""

import ctypes
import sys


def read_shortcut(path: str) -> tuple[str, str, str]:
    """返回快捷方式的目标、原始参数和工作目录。

    Raises:
        ValueError: 当前系统不支持 Windows 快捷方式。
        OSError: Windows 无法读取快捷方式。
    """
    if sys.platform != "win32":
        raise ValueError("当前系统不支持 Windows 快捷方式")

    import pythoncom
    from win32com.shell import shell

    # 为本次读取配对初始化和释放，保留 GUI 已有的 COM 状态。
    ole = ctypes.OleDLL("ole32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    ole.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    shortcut = None
    try:
        shortcut = pythoncom.CoCreateInstance(
            shell.CLSID_ShellLink,
            None,
            pythoncom.CLSCTX_INPROC_SERVER,
            shell.IID_IShellLink,
        )
        shortcut.QueryInterface(pythoncom.IID_IPersistFile).Load(path)
        # Windows 命令行上限为 32767 字符，避免接口默认的 1024 字符截断。
        arguments = shortcut.GetArguments(32768)
        if len(arguments.encode("utf-16-le")) // 2 >= 32767:
            raise ValueError("快捷方式的启动参数过长，无法完整导入")
        return (
            shortcut.GetPath(0, 32768)[0],
            arguments,
            shortcut.GetWorkingDirectory(32768),
        )
    except pythoncom.com_error as exc:
        raise OSError(f"无法读取快捷方式：{exc}") from exc
    finally:
        shortcut = None
        ole.CoUninitialize()
