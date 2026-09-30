# -*- coding: utf-8 -*-
"""提醒：开关生效、紧急提醒的特殊待遇、课堂事件能正确触发"""
import json, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOME"] = tempfile.mkdtemp()

import Scripts.Notify as N
SYS, SND = [], []
N.system_notify = lambda t, m: SYS.append((t, m)) or True
N.play_sound = lambda urgent=False: SND.append(urgent)

import Scripts.App as A
import Scripts.Classes as C

# ------------------------------------------------ Notifier 本身
cfg = {"notify_config": {}}
toasts, raised = [], []
n = N.Notifier(lambda: cfg, show_toast=toasts.append, raise_window=lambda: raised.append(1))

assert n.notify("problem", "t", "m") is True
assert SYS and SND == [False] and len(toasts) == 1 and not raised
print("✓ 默认全开：系统通知 + 提示音 + 浮窗都发出，普通提醒不抢焦点")

cfg["notify_config"] = {"problem": False}
SYS.clear(); SND.clear(); toasts.clear()
assert n.notify("problem", "t", "m") is False and not SYS and not SND and not toasts
print("✓ 按类别关闭后，该类提醒完全不发")

cfg["notify_config"] = {"enabled": False}
assert n.notify("callme", "t", "m", urgent=True) is False
assert n.notify("problem", "t", "m", force=True) is True     # 设置页「试一下」
print("✓ 总开关关闭后连紧急提醒也不发；force 可用于设置页试听")

cfg["notify_config"] = {"toast": False, "sound": False}
SYS.clear(); SND.clear(); toasts.clear(); raised.clear()
n.notify("callme", "点到你了", "m", urgent=True)
assert len(toasts) == 1, "紧急提醒即使关了浮窗也必须显示"
assert raised == [1], "紧急提醒应把窗口拉到最前"
assert SND == [], "关掉提示音就不该响"
print("✓ 紧急提醒（点名）无视浮窗开关并前置窗口，但仍尊重提示音开关")

# ------------------------------------------------ 课堂事件 -> 提醒
C.get_user_info = lambda s: (0, {"id": 1, "name": "唐琦"})
class Resp:
    def __init__(s, p, h=None):
        s.text = json.dumps(p); s.status_code = 200; s.headers = h or {}; s.content = b""
C.http_post = lambda *a, **k: Resp({"code": 0})
C.http_get = lambda *a, **k: Resp({"code": 0, "data": {"slides": []}})
C.call_ai = lambda cfg, img, prompt=None, timeout=None: ["A"]

EVENTS = []
app = A.App(emit=lambda e, d: EVENTS.append((e, d)))
app.notifier.show_toast = lambda payload: EVENTS.append(("toast", payload))
def notified(kind=None):
    return [d for e, d in EVENTS if e == "toast" and (kind is None or d["kind"] == kind)]

def lesson(mode="saved"):
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
calls = notified("callme")
assert len(calls) == 1 and calls[0]["urgent"] is True, EVENTS
print("✓ 点名：只有点到自己才提醒，且为紧急")

for mode, hint in (("notify", "自己作答"), ("saved", "还没保存答案")):
    EVENTS.clear()
    lesson(mode).handle_pushed_problem("p", 30)
    time.sleep(0.2)
    got = notified("problem")
    assert len(got) == 1, (mode, EVENTS)
    assert hint in (got[0]["title"] + got[0]["message"]), got[0]
    assert got[0]["target"]["problemId"] == "p", "提醒要能点开对应题目"
print("✓ 推题：需要你动手的两种情况也会提醒，且带跳转目标")

EVENTS.clear()
L = lesson()
L.on_message(ws, json.dumps({"op": "lessonfinished"}))
assert any(t["kind"] == "lesson" and "下课" in t["title"] for t in notified()), EVENTS
print("✓ 下课提醒")

EVENTS.clear()
app.config["sessionid"] = "x"
import Scripts.Utils as U
app.login_state = "ok"
U.get_user_info = lambda s: (_ for _ in ()).throw(Exception("未登录"))
A.get_user_info = U.get_user_info
app.probe_login()
assert app.login_state == "expired"
assert any(t["kind"] == "login" and t["urgent"] for t in notified()), EVENTS
print("✓ 登录失效：状态变为 expired 并发紧急提醒")

import requests
A.get_user_info = lambda s: (_ for _ in ()).throw(requests.exceptions.ConnectionError("no net"))
app.probe_login()
assert app.login_state == "offline", "网络异常不该误报为登录过期"
print("✓ 网络异常与登录失效区分开")

app.shutdown()
print("\n提醒全部通过")
