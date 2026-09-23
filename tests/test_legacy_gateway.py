# -*- coding: utf-8 -*-
"""老网关只认废弃的 budget_tokens 时，应自动回退一次"""
import json, os, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOME"] = tempfile.mkdtemp()

from PIL import Image
from Scripts.AI import AIError, call_ai

IMG = os.path.join(tempfile.mkdtemp(), "q.jpg")
Image.new("RGB", (30, 20), "white").save(IMG)
BODIES = []
MODE = {"v": "legacy"}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        BODIES.append(body)
        if MODE["v"] == "legacy" and "output_config" in body:
            return self._send(400, {"error": {"message":
                "thinking.type: adaptive is not supported; use budget_tokens"}})
        if MODE["v"] == "badmodel":
            return self._send(400, {"error": {"message": "model_not_found: no such model"}})
        self._send(200, {"content": [{"type": "text", "text": '{"answer": ["B"]}'}]})
    def _send(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]
cfg = {"ai_config": {"provider": "anthropic", "api_key": "k", "base_url": BASE,
                     "model": "glm-x", "thinking_effort": "high"}}

assert call_ai(cfg, IMG) == ["B"]
assert len(BODIES) == 2, "应当先试新写法、再回退一次，实际请求 %d 次" % len(BODIES)
assert BODIES[0]["thinking"] == {"type": "adaptive"} and "output_config" in BODIES[0]
assert BODIES[1]["thinking"]["type"] == "enabled" and BODIES[1]["thinking"]["budget_tokens"] == 16384
assert BODIES[1]["max_tokens"] > BODIES[1]["thinking"]["budget_tokens"]
assert "output_config" not in BODIES[1]
print("✓ 老网关拒绝 adaptive 时，自动回退到 budget_tokens 并成功")

# 与思考无关的 400 不应触发回退
BODIES.clear(); MODE["v"] = "badmodel"
try:
    call_ai(cfg, IMG); assert False
except AIError as e:
    assert "model_not_found" in str(e), e
assert len(BODIES) == 1, "无关的 400 不该重试，实际 %d 次" % len(BODIES)
print("✓ 与思考参数无关的 400 不会误触发回退，直接报错")
print("\n老网关兼容全部通过")
