from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from ctypes import cast, POINTER

def set_mute(mute_status):
    devices = AudioUtilities.GetSpeakers()
    interface = cast(devices.Activate(
        IAudioEndpointVolume._iid_, 0, None), POINTER(IAudioEndpointVolume))
    interface.SetMute(mute_status, None)
    print(f"系统已{'静音' if mute_status else '恢复声音'}")

if __name__ == "__main__":
    set_mute(True)