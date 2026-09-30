# -*- coding: utf-8 -*-
"""提醒：系统通知 + 提示音（与界面无关的部分）。

三路互相独立、尽力而为：系统通知可能被用户关掉，提示音可能没有播放器，
但只要有一路送达就不会错过。点到自己的名属于「紧急」，会额外把主窗口
拉到最前并连响几次。
"""
import os
import platform
import shutil
import subprocess
import threading

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


def play_sound(urgent=False):
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

    threading.Thread(target=work, daemon=True).start()


class Notifier:
    """按设置分发提醒。系统通知与提示音在这里发；界面内浮窗、窗口前置交给回调。

    notify() 可以从任意线程调用。
    """

    def __init__(self, get_config, show_toast=None, raise_window=None):
        self.get_config = get_config
        self.show_toast = show_toast
        self.raise_window = raise_window

    def settings(self):
        cfg = default_config()
        cfg.update((self.get_config() or {}).get("notify_config") or {})
        return cfg

    def notify(self, kind, title, message, urgent=False, target=None, force=False):
        """返回是否实际发出。force 供设置页的「试一下」使用。"""
        cfg = self.settings()
        if not force and (not cfg.get("enabled", True) or not cfg.get(kind, True)):
            return False
        if cfg.get("system", True):
            system_notify(title, message)
        if cfg.get("sound", True):
            play_sound(urgent)
        # 紧急提醒即使关了浮窗也要显示：点名是不能错过的
        if self.show_toast and (cfg.get("toast", True) or urgent):
            self.show_toast({"kind": kind, "title": title, "message": message,
                             "urgent": bool(urgent), "target": target})
        if urgent and self.raise_window:
            self.raise_window()
        return True
