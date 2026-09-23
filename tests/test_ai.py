# -*- coding: utf-8 -*-
"""用本地假 HTTP 服务验证 AI 调用链（请求格式、解析、错误映射、重试）"""
import base64, json, os, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOME"] = tempfile.mkdtemp()

from PIL import Image
from Scripts.AI import AIError, call_ai, call_glm, test_connection

IMG = os.path.join(tempfile.mkdtemp(), "q.jpg")
Image.new("RGB", (40, 30), "white").save(IMG)

MODE = {"v": "ok"}
SEEN = {}
FAILS = {"n": 0}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN["body"] = body; SEEN["headers"] = dict(self.headers)
        m = MODE["v"]
        if m == "401":   return self._send(401, {"error": "bad key"})
        if m == "429":   return self._send(429, {"error": "rate limited"})
        if m == "flaky":
            FAILS["n"] += 1
            if FAILS["n"] <= 2:                      # 前两次断连，第三次成功
                self.close_connection = True; return
            return self._send(200, self._answer('{"answer": ["C"]}'))
        if m == "prose": return self._send(200, self._answer(
            '好的，我来分析。\n```json\n{{"answer": "AB"}}\n```\n以上，因为……'))
        if m == "empty": return self._send(200, {"content": [{"type": "text", "text": ""}]})
        return self._send(200, self._answer('{"question": "x", "answer": ["B"]}'))
    @staticmethod
    def _answer(text): return {"content": [{"type": "text", "text": text}]}
    def _send(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw))); self.end_headers()
        self.wfile.write(raw)

srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]
cfg = {"ai_config": {"provider": "glm", "api_key": "sk-x", "base_url": BASE,
                     "model": "glm-test", "enable_thinking": False}}

# 1) 正常返回
assert call_ai(cfg, IMG) == ["B"]
print("✓ 正常应答：解析出答案 ['B']")

# 2) 请求格式：图片以 base64 块发出、鉴权头齐全、关闭思考时带 thinking:disabled
b = SEEN["body"]
assert b["model"] == "glm-test" and b["thinking"] == {"type": "disabled"}
img_block = b["messages"][0]["content"][0]
assert img_block["type"] == "image" and img_block["source"]["media_type"] == "image/jpeg"
assert base64.b64decode(img_block["source"]["data"])[:2] == b"\xff\xd8"   # 是真 JPEG
assert SEEN["headers"]["x-api-key"] == "sk-x"
assert SEEN["headers"]["Authorization"] == "Bearer sk-x"
assert SEEN["headers"]["anthropic-version"] == "2023-06-01"
print("✓ 请求体：图片 base64 + 模型 + 鉴权头 + thinking 开关都正确")

# 3) 模型啰嗦返回（代码块 + 双大括号 + 后置解析文字 + 连写多选）
MODE["v"] = "prose"
assert call_ai(cfg, IMG) == ["A", "B"]
print("✓ 啰嗦返回：剥离代码块/双大括号/解析文字，'AB' 拆成 ['A','B']")

# 4) 空正文（thinking 吃光 token）——给出可操作的提示
MODE["v"] = "empty"
try: call_ai(cfg, IMG); assert False
except AIError as e: assert "关闭思考模式" in str(e), e
print("✓ 空正文：报错提示「可尝试关闭思考模式」")

# 5) 401 / 429 映射成人话
MODE["v"] = "401"
try: call_ai(cfg, IMG); assert False
except AIError as e: assert "API Key 无效" in str(e), e
MODE["v"] = "429"
try: call_ai(cfg, IMG); assert False
except AIError as e: assert "限流" in str(e) and "并发" in str(e), e
print("✓ 401/429：映射为可读中文提示，而不是裸状态码")

# 6) 连接抖动自动重试
MODE["v"] = "flaky"
assert call_ai(cfg, IMG) == ["C"] and FAILS["n"] == 3
print("✓ 连接抖动：前两次失败后自动重试成功（共 3 次）")

# 7) 缺图 / 缺 Key 的前置校验
MODE["v"] = "ok"
try: call_ai(cfg, "/不存在.jpg"); assert False
except AIError as e: assert "截图缺失" in str(e), e
try: call_ai({"ai_config": {"api_key": ""}}, IMG); assert False
except AIError as e: assert "API Key" in str(e), e
print("✓ 前置校验：缺截图 / 缺 Key 时给出明确提示，不发无效请求")

# 8) 测试连接按钮
assert "可用" in test_connection(cfg["ai_config"])
MODE["v"] = "401"
try: test_connection(cfg["ai_config"]); assert False
except AIError as e: assert "API Key 无效" in str(e)
print("✓ 测试连接：成功/失败两条路径都正确")
print("\nAI 层全部通过")
