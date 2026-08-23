"""关机确认窗：倒计时结束或点「立即关机」→ 退出码 0（确认）；关窗/取消 → 退出码 1。

仅 Windows 下由 utils_shutdown._run_shutdown_confirm 以 CREATE_NO_WINDOW 子进程拉起，
实际关机动作由调用方（shutdown_sys）执行，本脚本只负责「确认 / 取消」。
"""

import sys
import tkinter as tk


def main(countdown: int) -> int:
    """
    弹出倒计时确认窗并等待用户选择。
    :param countdown: 倒计时秒数，归零时自动确认关机
    :return: 0 表示确认关机，1 表示取消
    """
    print(f"Tk 初始化中 TkVersion={tk.TkVersion}", flush=True)
    try:
        root = tk.Tk()
    except Exception as e:  # 无显示器/桌面等环境 Tk 无法创建
        print(f"Tk 初始化失败 {e!r}", flush=True)
        return 1
    print("Tk 创建成功", flush=True)
    root.title("即将关机")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    width, height = 380, 170
    root.geometry(
        f"{width}x{height}"
        f"+{(root.winfo_screenwidth() - width) // 2}"
        f"+{(root.winfo_screenheight() - height) // 2}"
    )

    confirmed = {"value": False}

    def do_shutdown() -> None:
        confirmed["value"] = True
        try:
            root.destroy()
        except Exception as e:
            print(f"root.destroy 失败 {e!r}", flush=True)

    def on_cancel() -> None:
        confirmed["value"] = False
        try:
            root.destroy()
        except Exception as e:
            print(f"root.destroy 失败 {e!r}", flush=True)

    label = tk.Label(root, text="", font=("Microsoft YaHei", 13))
    label.pack(expand=True)

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=12)
    tk.Button(btn_frame, text="立即关机", width=12, command=do_shutdown).pack(
        side="left", padx=10
    )
    tk.Button(btn_frame, text="取消", width=12, command=on_cancel).pack(
        side="left", padx=10
    )

    remain = {"value": countdown}

    def tick() -> None:
        if not root.winfo_exists():
            return
        remain["value"] -= 1
        if remain["value"] <= 0:
            do_shutdown()
            return
        label.config(text=f"系统将在 {remain['value']} 秒后关机")
        root.after(1000, tick)

    root.protocol("WM_DELETE_WINDOW", on_cancel)
    label.config(text=f"系统将在 {countdown} 秒后关机")
    root.after(1000, tick)
    root.mainloop()

    print(f"确认窗结束 confirmed={confirmed['value']}", flush=True)
    return 0 if confirmed["value"] else 1


if __name__ == "__main__":
    countdown = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    sys.exit(main(countdown))
