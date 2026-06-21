import os
import tkinter as tk
from tkinter import messagebox
import threading
import time

def start_shutdown():
    # 执行关机命令
    os.system("shutdown /s /t 0")

def countdown_and_close(root, label, seconds):
    if seconds > 0:
        label.config(text=f"电脑将在 {seconds} 秒后关机\n请保存好您的工作！")
        # 每隔1秒更新一次倒计时
        root.after(1000, countdown_and_close, root, label, seconds - 1)
    else:
        root.destroy()
        start_shutdown()

def on_closing():
    # 如果用户直接点红叉关闭窗口，默认也取消关机（或者你可以改为执行关机）
    root.destroy()

# 创建主窗口
root = tk.Tk()
root.title("关机提醒")
root.attributes("-topmost", True)  # 窗口置顶
root.geometry("300x150")

# 设置提示文字
label = tk.Label(root, text="", font=("Microsoft YaHei", 12), pady=20)
label.pack()

# 按钮容器
btn_frame = tk.Frame(root)
btn_frame.pack(pady=10)

# 确定按钮：立即关机
btn_ok = tk.Button(btn_frame, text="立即关机", width=10, command=lambda: [root.destroy(), start_shutdown()])
btn_ok.pack(side="left", padx=10)

# 取消按钮：中止任务
btn_cancel = tk.Button(btn_frame, text="取消", width=10, command=root.destroy)
btn_cancel.pack(side="right", padx=10)

# 启动倒计时（30秒）
countdown_and_close(root, label, 30)

root.protocol("WM_DELETE_WINDOW", on_closing)
root.mainloop()