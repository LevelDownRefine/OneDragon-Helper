"""关机倒计时窗口：45 秒倒计时结束即关机，关闭窗口则直接结束进程。"""

import os
import subprocess
import tkinter as tk


def main() -> None:
    remaining = 45

    def tick() -> None:
        nonlocal remaining
        if remaining <= 0:
            root.destroy()
            return
        label.config(text=f"电脑将在 {remaining} 秒后关机")
        remaining -= 1
        root.after(1000, tick)

    root = tk.Tk()
    root.title("关机倒计时")
    root.attributes("-topmost", True)
    label = tk.Label(root, text="", font=("Microsoft YaHei", 16))
    label.pack(padx=40, pady=40)

    # 用户关窗：直接结束进程，不会走到下方的关机代码
    root.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))
    tick()
    root.mainloop()

    # 只有倒计时正常走完才会到这里
    subprocess.run(["shutdown", "/s", "/f", "/t", "0"], check=False)


if __name__ == "__main__":
    main()
