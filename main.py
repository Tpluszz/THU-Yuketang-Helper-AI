# -*- coding: utf-8 -*-
"""清华大学雨课堂助手 - 程序入口。"""
import os
import platform
import sys
import tkinter as tk
import traceback
from tkinter import messagebox

# 以脚本所在目录为基准，保证双击运行时也能找到 UI / Scripts 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def enable_hidpi():
    """Windows 上开启 DPI 感知，避免高分屏界面发虚。"""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    enable_hidpi()
    root = tk.Tk()
    root.title("清华大学雨课堂助手")
    root.withdraw()          # 先藏起来，等界面搭好再显示，避免闪白

    try:
        from UI.MainWindow import MainWindow
        MainWindow(root)
    except Exception:
        root.destroy()
        detail = traceback.format_exc()
        print(detail, file=sys.stderr)
        try:
            messagebox.showerror("启动失败", "程序启动时出错：\n\n%s" % detail[-1200:])
        except Exception:
            pass
        return 1

    root.deiconify()
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
