# -*- coding: utf-8 -*-
"""验证四种接口格式的请求体与返回解析（对着本地假服务）"""
import json, os, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOME"] = tempfile.mkdtemp()

from PIL import Image
from Scripts.AI import AIError, PROVIDERS, call_ai, normalize_provider, test_connection

IMG = os.path.join(tempfile.mkdtemp(), "q.jpg")
Image.new("RGB", (40, 30), "white").save(IMG)
SEEN = {}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN["path"], SEEN["body"], SEEN["headers"] = self.path, body, dict(self.headers)
        if self.path == "/v1/messages":
            out = {"content": [{"type": "thinking", "thinking": "嗯…"},
                               {"type": "text", "text": '{"answer": ["B"]}'}]}
        elif self.path == "/v1/responses":
            out = {"status": "completed", "output": [
                {"type": "reasoning", "summary": []},
                {"type": "message", "content": [{"type": "output_text", "text": '{"answer": ["C"]}'}]}]}
        elif self.path == "/v1/chat/completions":
            out = {"choices": [{"message": {"content": '```json\n{"answer": ["D"]}\n```'}}]}
        else:
            self.send_response(404); self.end_headers(); return
        raw = json.dumps(out).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]

def cfg(provider, **kw):
    d = {"provider": provider, "api_key": "sk-x", "base_url": BASE,
         "model": "m-test", "enable_thinking": True}
    d.update(kw); return {"ai_config": d}

# --- Anthropic
assert call_ai(cfg("anthropic"), IMG) == ["B"]
assert SEEN["path"] == "/v1/messages"
assert SEEN["body"]["messages"][0]["content"][0]["type"] == "image"
assert SEEN["headers"]["anthropic-version"] == "2023-06-01"
print("✓ anthropic：打到 /v1/messages，图片用 base64 source，跳过 thinking 块取正文")

# --- Responses（Codex）
assert call_ai(cfg("openai_responses"), IMG) == ["C"]
assert SEEN["path"] == "/v1/responses"
c = SEEN["body"]["input"][0]["content"]
assert c[0]["type"] == "input_image" and c[0]["image_url"].startswith("data:image/jpeg;base64,")
assert c[1]["type"] == "input_text"
assert SEEN["body"]["max_output_tokens"] == 4096 and SEEN["body"]["reasoning"]["effort"] == "medium"
assert "anthropic-version" not in SEEN["headers"]
print("✓ openai_responses：打到 /v1/responses，input_image/input_text，跳过 reasoning 条目")

assert call_ai(cfg("openai_responses", enable_thinking=False), IMG) == ["C"]
assert SEEN["body"]["reasoning"]["effort"] == "low"
print("✓ openai_responses：关闭思考时 reasoning.effort 降为 low")

# --- Chat Completions
assert call_ai(cfg("openai_chat"), IMG) == ["D"]
assert SEEN["path"] == "/v1/chat/completions"
assert SEEN["body"]["messages"][0]["content"][0]["type"] == "image_url"
print("✓ openai_chat：打到 /v1/chat/completions，image_url 内联 data URI")

# --- 老配置名兼容
assert call_ai(cfg("glm"), IMG) == ["B"], "老的 provider=glm 应当仍然可用"
assert normalize_provider("codex") == "openai_responses"
print("✓ 兼容：老配置 provider=glm 仍走 Anthropic；codex 归一到 Responses")

# --- Base URL 带尾斜杠/路径残留
assert call_ai(cfg("anthropic", base_url=BASE + "/"), IMG) == ["B"]
print("✓ Base URL 末尾斜杠会被正确去掉")

# --- 404 提示要能指出格式选错了
try:
    call_ai(cfg("anthropic", base_url=BASE + "/wrong"), IMG); assert False
except AIError as e:
    assert "404" in str(e) and "接口格式" in str(e), e
print("✓ 地址/格式不匹配时，404 提示会点明去检查 Base URL 与接口格式")

# --- 测试连接覆盖三种 HTTP 格式
for p in ("anthropic", "openai_responses", "openai_chat"):
    assert "可用" in test_connection(cfg(p)["ai_config"]), p
print("✓ 测试连接：三种 HTTP 格式都能打通")
print("\n四种接口格式全部通过")
