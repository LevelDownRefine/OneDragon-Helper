import logging
from ctypes import POINTER, cast

from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

logger = logging.getLogger(__name__)


def set_mute(mute_status):
    devices = AudioUtilities.GetSpeakers()
    interface = cast(devices.Activate(
        IAudioEndpointVolume._iid_, 0, None), POINTER(IAudioEndpointVolume))
    interface.SetMute(mute_status, None)
    logger.info(f"系统已{'静音' if mute_status else '恢复声音'}")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    set_mute(True)
