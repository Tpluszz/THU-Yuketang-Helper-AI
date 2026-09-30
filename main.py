# -*- coding: utf-8 -*-
"""清华大学雨课堂助手 — 程序入口。

界面是一个本地 HTML 页面，跑在系统自带的浏览器内核里（macOS 用 WebKit，
Windows 用 WebView2），通过 pywebview 与 Python 通信。
"""
import os
import platform
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def enable_hidpi():
    """Windows 上开启 DPI 感知，避免高分屏发虚。"""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def fatal(message):
    print(message, file=sys.stderr)
    try:
        if platform.system() == "Darwin":
            import subprocess
            subprocess.run(["osascript", "-e",
                            'display alert "雨课堂助手启动失败" message %s'
                            % ('"%s"' % message.replace('"', "'")[:500])])
    except Exception:
        pass


def main():
    enable_hidpi()
    try:
        import webview
    except ImportError:
        fatal("缺少界面依赖 pywebview。请先运行：pip install -r requirements.txt")
        return 1

    from Bridge import Bridge

    bridge = Bridge()
    window = webview.create_window(
        "雨课堂助手",
        resource("web", "index.html"),
        js_api=bridge,
        width=1180, height=820, min_size=(900, 620),
        background_color="#F6F5F8",
        text_select=False,
    )
    bridge._attach(window)
    window.events.closed += bridge._shutdown

    debug = "--debug" in sys.argv
    try:
        webview.start(debug=debug)
    except Exception:
        traceback.print_exc()
        fatal("界面启动失败，详情见终端输出")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
