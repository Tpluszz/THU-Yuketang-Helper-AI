# -*- coding: utf-8 -*-
"""超时必须真的可控：默认参数绑定过的话，外部改 TIMEOUT 会静默失效"""
import json, os, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOME"] = tempfile.mkdtemp()

from PIL import Image
import Scripts.AI as A
from Scripts.AI import AIError, call_ai

IMG = os.path.join(tempfile.mkdtemp(), "q.jpg")
Image.new("RGB", (20, 20), "white").save(IMG)

class Slow(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        time.sleep(30)                      # 永远比超时长
        self.send_response(200); self.end_headers()
srv = HTTPServer(("127.0.0.1", 0), Slow)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]

def cfg(**kw):
    d = {"provider": "anthropic", "api_key": "k", "base_url": BASE,
         "model": "m", "thinking_effort": "low"}
    d.update(kw); return {"ai_config": d}

A.MAX_RETRY = 0

# 1) 逐次调用传入的 timeout 必须生效
t = time.time()
try:
    call_ai(cfg(), IMG, timeout=3); assert False, "不该成功"
except AIError:
    pass
dt = time.time() - t
assert dt < 8, "传入 timeout=3 却等了 %.1fs，说明没生效" % dt
print("✓ 每次调用传入的 timeout 生效（%.1fs 就返回）" % dt)

# 2) 模块常量 TIMEOUT 必须可被外部覆盖（默认参数绑定过就不行）
A.TIMEOUT = 2
t = time.time()
try:
    call_ai(cfg(), IMG); assert False
except AIError:
    pass
dt = time.time() - t
assert dt < 7, "改 TIMEOUT=2 却等了 %.1fs —— 默认参数在 def 时被绑死了" % dt
print("✓ 模块常量 TIMEOUT 可被外部覆盖（%.1fs 就返回）" % dt)

# 3) 课上答题：超时必须由题目剩余时间推导，而不是默认的 120s
A.TIMEOUT = 120
import Scripts.Classes as C
captured = {}
def fake_call_ai(config, image, prompt=None, timeout=None):
    captured["timeout"] = timeout
    return ["A"]
C.call_ai = fake_call_ai
C.get_user_info = lambda s: (0, {"id": 1, "name": "x"})
class Resp:
    def __init__(s, p, h=None): s.text=json.dumps(p); s.status_code=200; s.headers=h or {}; s.content=b""
C.http_post = lambda *a, **k: Resp({"code": 0})
C.http_get = lambda *a, **k: Resp({"code": 0, "data": {"slides": []}})
class UIm:
    config = {"sessionid":"s","auto_danmu":False,
              "answer_config":{"answer_delay":{"type":2,"custom":{"time":0}},"mode":"ai_auto"},
              "ai_config":{"api_key":"k","provider":"anthropic"}}
    def add_message(self,*a,**k): pass
    def on_lesson_updated(self,l): pass

for limit, want in ((40, 35), (-1, None), (8, A.MIN_TIMEOUT)):
    captured.clear()
    L = C.Lesson("L","课","R",UIm())
    L.problems_ls=[{"problemId":"p","problemType":1,"page":1,"answers":[],
                    "options":[{"key":"A","value":"a"}],"image":__file__}]
    L.handle_pushed_problem("p", limit); time.sleep(0.4)
    got = captured.get("timeout")
    assert got == want, "limit=%s 期望超时 %s，实际 %s" % (limit, want, got)
    print("  limit=%-4s -> AI 超时 %s" % (limit, got if got is not None else "不限（用默认）"))
print("✓ 课上答题的 AI 超时由题目剩余时间推导，限时题不会等满默认超时")

# 4) 硬性总时限：服务端持续滴水般回字节时，requests 的 read timeout 永远不触发
#    （实测网关上出现过一次调用跑 748 秒）
import socket
class Dribble(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        # 每秒吐一个 chunk，永不结束：读取间隔始终 < timeout
        try:
            while True:
                self.wfile.write(b"1\r\n \r\n"); self.wfile.flush()
                time.sleep(1)
        except Exception:
            pass

srv2 = HTTPServer(("127.0.0.1", 0), Dribble)
threading.Thread(target=srv2.serve_forever, daemon=True).start()
BASE2 = "http://127.0.0.1:%d" % srv2.server_address[1]

A.TIMEOUT = 120
t = time.time()
try:
    A.call_ai({"ai_config": {"provider": "anthropic", "api_key": "k", "base_url": BASE2,
                             "model": "m", "thinking_effort": "low"}}, IMG, timeout=5)
    raise SystemExit("✗ 竟然成功返回了")
except AIError as e:
    dt = time.time() - t
    assert dt < 20, "滴水式挂起没被切断，等了 %.1fs（这正是 748 秒那次的成因）" % dt
    print("✓ 滴水式挂起被硬时限切断（%.1fs，预算 5s）" % dt)
print("\n超时控制全部通过")
