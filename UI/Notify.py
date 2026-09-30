# -*- coding: utf-8 -*-
"""提醒：系统通知 + 提示音 + 程序内浮窗。

三路互相独立、尽力而为：系统通知可能被用户关掉，提示音可能没有播放器，
但只要有一路送达就不会错过。点到自己的名属于「紧急」，会额外把主窗口
拉到最前并连响几次。
"""
import os
import platform
import shutil
import subprocess
import threading
import tkinter as tk

from UI import Theme

SYSTEM = platform.system()

# 提醒类别 -> (设置页里的名字, 默认是否开启)
KINDS = {
    "problem": ("老师推送新题目", True),
    "callme":  ("点名点到我", True),
    "confirm": ("AI 答完等我确认", True),
    "lesson":  ("上课签到 / 下课", True),
    "login":   ("登录失效", True),
}

TOAST_SECONDS = 7
MAX_TOASTS = 4

_MAC_SOUNDS = {"normal": "Glass", "urgent": "Sosumi"}


def default_config():
    cfg = {"enabled": True, "sound": True, "system": True, "toast": True}
    cfg.update({k: default for k, (_, default) in KINDS.items()})
    return cfg


def _applescript_str(text):
    return '"%s"' % str(text).replace("\\", "\\\\").replace('"', '\\"')


def _run_quiet(args):
    """后台起一个子进程，不等它、不关心结果。"""
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)
        return True
    except (OSError, ValueError):
        return False


def system_notify(title, message):
    """发一条操作系统通知，失败静默。"""
    if SYSTEM == "Darwin":
        script = "display notification %s with title %s" % (
            _applescript_str(message), _applescript_str(title))
        return _run_quiet(["osascript", "-e", script])
    if SYSTEM == "Linux" and shutil.which("notify-send"):
        return _run_quiet(["notify-send", "-a", "雨课堂助手", title, message])
    if SYSTEM == "Windows":
        # 不引入第三方依赖：用 PowerShell 调 WinForms 的托盘气泡
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$n=New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon=[System.Drawing.SystemIcons]::Information;"
            "$n.Visible=$true;"
            "$n.ShowBalloonTip(6000,'%s','%s',[System.Windows.Forms.ToolTipIcon]::Info);"
            "Start-Sleep -Seconds 7;$n.Dispose()"
        ) % (title.replace("'", "''"), message.replace("'", "''"))
        return _run_quiet(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps])
    return False


def play_sound(urgent=False, fallback=None):
    """播放提示音；紧急提醒连响三次。"""
    times = 3 if urgent else 1

    def work():
        for _ in range(times):
            ok = False
            if SYSTEM == "Darwin":
                name = _MAC_SOUNDS["urgent" if urgent else "normal"]
                path = "/System/Library/Sounds/%s.aiff" % name
                if os.path.exists(path):
                    ok = subprocess.call(["afplay", path], stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL) == 0
            elif SYSTEM == "Windows":
                try:
                    import winsound
                    if urgent:
                        winsound.Beep(1200, 300)
                    else:
                        winsound.MessageBeep(winsound.MB_ICONASTERISK)
                    ok = True
                except Exception:
                    ok = False
            else:
                for player, sound in (("paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"),
                                      ("aplay", "/usr/share/sounds/alsa/Front_Center.wav")):
                    if shutil.which(player) and os.path.exists(sound):
                        ok = subprocess.call([player, sound], stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL) == 0
                        break
            if not ok and fallback:
                fallback()

    threading.Thread(target=work, daemon=True).start()


class Notifier:
    """主窗口持有一个实例；notify() 可以从任意线程调用。"""

    def __init__(self, root, get_config):
        self.root = root
        self.get_config = get_config
        self.toasts = []
        self._closed = False

    def close(self):
        self._closed = True

    def settings(self):
        cfg = default_config()
        cfg.update((self.get_config() or {}).get("notify_config") or {})
        return cfg

    def notify(self, kind, title, message, urgent=False, on_click=None):
        """按设置分发一条提醒。返回是否实际发出（便于测试）。"""
        cfg = self.settings()
        if not cfg.get("enabled", True) or not cfg.get(kind, True):
            return False
        if cfg.get("system", True):
            system_notify(title, message)
        if cfg.get("sound", True):
            play_sound(urgent, fallback=self._bell)
        if cfg.get("toast", True) or urgent:
            self._ui(lambda: self._show_toast(title, message, urgent, on_click))
        if urgent:
            self._ui(self._raise_main)
        return True

    # ------------------------------------------------------------ 主线程部分

    def _ui(self, func):
        if self._closed:
            return
        try:
            self.root.after(0, func)
        except (tk.TclError, RuntimeError):
            pass

    def _bell(self):
        self._ui(lambda: self.root.bell())

    def _raise_main(self):
        """把主窗口拉到最前。topmost 只开一下，免得一直霸屏。"""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(1500, lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except tk.TclError:
            pass

    def _show_toast(self, title, message, urgent, on_click):
        c = Theme.C
        # 清掉已经关闭的，控制同时显示的数量
        self.toasts = [t for t in self.toasts if t.winfo_exists()]
        while len(self.toasts) >= MAX_TOASTS:
            self.toasts.pop(0).destroy()

        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        edge = c["danger"] if urgent else c["accent"]
        top.configure(bg=edge)

        body = tk.Frame(top, bg=c["surface"], padx=14, pady=10)
        body.pack(fill=tk.BOTH, expand=True, padx=(4, 1), pady=1)
        tk.Label(body, text=title, font=Theme.font(12, "bold"), bg=c["surface"],
                 fg=c["danger"] if urgent else c["text"], anchor=tk.W,
                 justify=tk.LEFT).pack(fill=tk.X)
        tk.Label(body, text=message, font=Theme.font(10), bg=c["surface"], fg=c["muted"],
                 anchor=tk.W, justify=tk.LEFT, wraplength=300).pack(fill=tk.X, pady=(3, 0))
        hint = "点击查看" if on_click else "点击关闭"
        tk.Label(body, text=hint, font=Theme.font(9), bg=c["surface"], fg=c["faint"],
                 anchor=tk.E).pack(fill=tk.X, pady=(4, 0))

        def clicked(_=None):
            try:
                top.destroy()
            except tk.TclError:
                pass
            if on_click:
                on_click()
            else:
                self._raise_main()

        for widget in (top, body, *body.winfo_children()):
            widget.bind("<Button-1>", clicked)

        self.toasts.append(top)
        self._layout_toasts()
        # 紧急提醒不自动消失，必须点掉
        if not urgent:
            top.after(TOAST_SECONDS * 1000, lambda: self._dismiss(top))

    def _dismiss(self, top):
        try:
            top.destroy()
        except tk.TclError:
            pass
        self._layout_toasts()

    def _layout_toasts(self):
        """右下角自下而上堆叠。"""
        self.toasts = [t for t in self.toasts if t.winfo_exists()]
        if not self.toasts:
            return
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        y = screen_h - 80
        for top in reversed(self.toasts):
            top.update_idletasks()
            w = max(320, top.winfo_reqwidth())
            h = top.winfo_reqheight()
            y -= h + 10
            top.geometry("%dx%d+%d+%d" % (w, h, screen_w - w - 24, y))
