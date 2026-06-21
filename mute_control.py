from pycaw.pycaw import AudioUtilities

def set_mute(mute_status):
    # 1. 获取设备包装对象
    devices = AudioUtilities.GetSpeakers()
    
    # 2. 直接访问已经封装好的 EndpointVolume 属性
    interface = devices.EndpointVolume
    
    # 3. 执行静音 (True 为 1，False 为 0)
    interface.SetMute(mute_status, None)
    
    print(f"系统已{'静音' if mute_status else '恢复声音'}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) <= 1 or sys.argv[1].lower() == "1":
        set_mute(True)
    elif sys.argv[1].lower() == "0":
        set_mute(False)