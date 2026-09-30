# -*- coding: utf-8 -*-
"""提醒、登录状态灯、打开即监听、配置原地重载"""
import json, os, sys, tempfile, threading, time, tkinter as tk
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOME"] = tempfile.mkdtemp()

import requests
import UI.Notify as N

# 打桩：测试时不真的弹系统通知、不真的响
SYS, SND = [], []
N.system_notify = lambda t, m: SYS.append((t, m)) or True
N.play_sound = lambda urgent=False, fallback=None: SND.append(urgent)

import Scripts.Classes as C
import UI.MainWindow as MW
from UI import Theme

C.get_user_info = lambda s: (0, {"id": 1, "name": "唐琦"})

class Resp:
    def __init__(s, p, h=None):
        s.text = json.dumps(p); s.status_code = 200; s.headers = h or {}; s.content = b""
C.http_post = lambda *a, **k: Resp({"code": 0})
C.http_get = lambda *a, **k: Resp({"code": 0, "data": {"slides": []}})

root = tk.Tk(); root.withdraw()
R = {}

def pump(sec=0.4):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.01)

# ------------------------------------------------ 1. Notifier 本身
cfg = {"notify_config": {}}
n = N.Notifier(root, lambda: cfg)
Theme.init(root, "light")
assert n.notify("problem", "t", "m") is True
pump()
assert SYS and SND == [False] and len(n.toasts) == 1
print("✓ 默认全开：系统通知、提示音、程序内浮窗都发出")

cfg["notify_config"] = {"problem": False}
SYS.clear(); SND.clear()
assert n.notify("problem", "t", "m") is False and not SYS and not SND
print("✓ 按类别关闭后，该类提醒完全不发")

cfg["notify_config"] = {"enabled": False}
assert n.notify("callme", "t", "m", urgent=True) is False
print("✓ 总开关关闭后，连紧急提醒也不发")

cfg["notify_config"] = {"toast": False}
before = len([t for t in n.toasts if t.winfo_exists()])
n.notify("callme", "点到你了", "m", urgent=True); pump()
after = len([t for t in n.toasts if t.winfo_exists()])
assert after == before + 1, "紧急提醒即使关了浮窗也应强制显示"
assert SND[-1] is True, "紧急提醒应使用紧急提示音"
print("✓ 紧急提醒（点名）无视「浮窗」开关强制显示，并用紧急提示音")

for _ in range(10):
    n.notify("problem", "t", "m")
pump()
assert len([t for t in n.toasts if t.winfo_exists()]) <= N.MAX_TOASTS
print("✓ 浮窗最多同时 %d 个，不会刷屏" % N.MAX_TOASTS)
for t in n.toasts:
    t.destroy()
n.close()

# ------------------------------------------------ 2. 主窗口集成
app = MW.MainWindow(root)
EVENTS = []
real_notify = app.notifier.notify
def spy(kind, title, message, urgent=False, on_click=None):
    EVENTS.append((kind, title, message, urgent, on_click))
    return real_notify(kind, title, message, urgent=urgent, on_click=on_click)
app.notifier.notify = spy
pump(0.8)

def lesson(mode="ai_auto"):
    app.config.setdefault("answer_config", {})["mode"] = mode
    L = C.Lesson("L1", "组合数学", "R", app)
    L.problems_ls = [{"problemId": "p", "problemType": 1, "page": 4, "body": "Q",
                      "options": [{"key": "A", "value": "a"}], "answers": [], "image": ""}]
    return L

ws = type("WS", (), {"send": lambda *a: None, "close": lambda *a: None})()

EVENTS.clear()
L = lesson()
L.on_message(ws, json.dumps({"op": "callpaused", "name": "唐琦"}))
L.on_message(ws, json.dumps({"op": "callpaused", "name": "别人"}))
pump()
calls = [e for e in EVENTS if e[0] == "callme"]
assert len(calls) == 1 and calls[0][3] is True, EVENTS
print("✓ 点名：点到自己才提醒且为紧急，点到别人不打扰")

for mode, hint in (("notify", "自己作答"), ("saved", "没保存答案")):
    EVENTS.clear()
    L = lesson(mode)
    L.handle_pushed_problem("p", 30); pump()
    probs = [e for e in EVENTS if e[0] == "problem"]
    assert len(probs) == 1 and hint in (probs[0][1] + probs[0][2]), (mode, EVENTS)
    assert probs[0][4] is not None, "推题提醒应能点击跳转"
print("✓ 推题：「只提示」「没保存答案」这两种需要你动手的情况也会提醒，且可点击跳转")

EVENTS.clear()
L = lesson()
L.on_message(ws, json.dumps({"op": "lessonfinished"})); pump()
assert any(e[0] == "lesson" and "下课" in e[1] for e in EVENTS), EVENTS
print("✓ 下课提醒")

# 点击提醒 -> 打开该课题目列表并直接打开那道题
L = lesson()
prob = L.problems_ls[0]
win = app.open_lesson(L, prob); pump()
assert win.alive() and str(prob["problemId"]) in win.detail_windows
assert win.detail_windows[str(prob["problemId"])].alive()
again = app.open_lesson(L, prob); pump()
assert again is win, "重复点击不应开出第二个窗口"
print("✓ 点提醒浮窗：打开对应课程的题目列表并直接定位到那道题，重复点击不重复开窗")
win.close()

# ------------------------------------------------ 3. 登录状态灯
app.set_login_state("none")
assert "未登录" in app.account_label.cget("text") and app.login_btn.cget("text") == "登录"
app.set_login_state("ok", "唐琦")
assert app.account_label.cget("text") == "已登录 · 唐琦" and app.login_btn.cget("text") == "切换账号"
print("✓ 状态灯：未登录 / 已登录·姓名，登录按钮文字随之变化")

app.config["sessionid"] = "x"
def boom_net(s): raise requests.exceptions.ConnectionError("no net")
C.get_user_info = boom_net
import Scripts.Utils as U; U.get_user_info = boom_net
app._probe_account(); pump()
assert app.login_state == "offline", app.login_state
print("✓ 网络异常时显示「暂时无法确认」，不会误报为登录过期")

def boom_auth(s): raise Exception("获取用户信息失败：未登录")
U.get_user_info = boom_auth
app.set_login_state("ok", "唐琦"); EVENTS.clear()
app._probe_account(); pump()
assert app.login_state == "expired" and app.login_btn.cget("text") == "重新登录"
assert any(e[0] == "login" and e[3] for e in EVENTS), "从已登录变为过期时应紧急提醒"
print("✓ 登录失效：状态灯变黄、按钮变「重新登录」，并发紧急提醒")

# ------------------------------------------------ 4. 打开即监听
U.get_user_info = lambda s: (0, {"id": 1, "name": "唐琦"})
started = []
app.toggle_monitor = lambda: started.append(True)
app.config["auto_monitor"] = False
app._probe_account(); pump()
assert not started
app.config["auto_monitor"] = True
app._probe_account(); pump()
assert started == [True]
print("✓ 打开即监听：开启后，确认登录有效才自动开始；关闭时不会自动开始")

U.get_user_info = boom_auth; started.clear()
app._probe_account(); pump()
assert not started, "登录无效时不应自动开始监听"
print("✓ 登录无效时即使开了「打开即监听」也不会启动")

# ------------------------------------------------ 5. 配置原地重载
ref = app.config
app.reload_config()
assert app.config is ref, "reload_config 换了新对象，正在上的课会读不到新设置"
print("✓ 配置原地重载：正在监听的课程与主窗口共用同一份配置")

root.destroy()
print("\n提醒 / 登录状态 / 自动监听 全部通过")
