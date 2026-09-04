"""运行中静音：系统静音执行（config 读写见 ``src.utils.utils_runner``）。

静音的「执行」由主仓在脚本链运行前后完成（覆盖异常/强制关闭窗口），
通过 ``set_system_mute`` 直接操作系统音频（Windows 专属，按需 import pycaw），
非 Windows / pycaw 缺失时安全降级为 False（不影响链运行）。
"""

import logging
import sys

logger = logging.getLogger(__name__)


def set_system_mute(mute_status: bool) -> bool:
    """设置系统扬声器静音状态（Windows 专属，按需 import pycaw）。

    Args:
        mute_status: True 静音，False 取消静音。

    Returns:
        成功执行返回 True；非 Windows 平台或 pycaw 不可用时返回 False。
    """
    if sys.platform != "win32":
        return False
    try:
        from ctypes import POINTER, cast

        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    except ImportError:
        return False
    devices = AudioUtilities.GetSpeakers()
    interface = cast(
        devices.Activate(IAudioEndpointVolume._iid_, 0, None),
        POINTER(IAudioEndpointVolume),
    )
    interface.SetMute(bool(mute_status), None)
    return True


def mute_on() -> None:
    """运行前静音（pre_run step）：开启系统静音，异常记日志不中断。"""
    try:
        set_system_mute(True)
    except Exception:
        logger.exception("[mute] 运行前静音失败")


def mute_off() -> None:
    """运行后恢复（post_run step）：关闭系统静音，异常记日志不中断。"""
    try:
        set_system_mute(False)
    except Exception:
        logger.exception("[mute] 运行后恢复声音失败")
