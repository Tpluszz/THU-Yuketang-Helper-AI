# -*- coding: utf-8 -*-
"""验证四种接口格式的请求体与返回解析（对着本地假服务）"""
import json, os, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOME"] = tempfile.mkdtemp()

from PIL import Image
from Scripts.AI import (AIError, EFFORTS, PROVIDERS, call_ai, effort_hint,
                        normalize_effort, normalize_provider, test_connection)

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
         "model": "m-test", "thinking_effort": "medium"}
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

assert call_ai(cfg("openai_responses", thinking_effort="off"), IMG) == ["C"]
assert "reasoning" not in SEEN["body"], "关闭时不该发送 reasoning 字段"
print("✓ openai_responses：关闭思考时干脆不发 reasoning 字段")

# xhigh 必须原样透传（能否用取决于模型，不是接口）
assert call_ai(cfg("openai_responses", thinking_effort="xhigh"), IMG) == ["C"]
assert SEEN["body"]["reasoning"]["effort"] == "xhigh", SEEN["body"]
assert call_ai(cfg("openai_chat", thinking_effort="xhigh"), IMG) == ["D"]
assert SEEN["body"]["reasoning_effort"] == "xhigh", SEEN["body"]
print("✓ xhigh 原样透传给 Responses / Chat，不被降档")

# Anthropic 用 budget_tokens 表达，且 max_tokens 必须大于预算
assert call_ai(cfg("anthropic", thinking_effort="xhigh"), IMG) == ["B"]
th = SEEN["body"]["thinking"]
assert th == {"type": "enabled", "budget_tokens": 24576}, th
assert SEEN["body"]["max_tokens"] > th["budget_tokens"], "max_tokens 必须大于思考预算"
assert call_ai(cfg("anthropic", thinking_effort="off"), IMG) == ["B"]
assert SEEN["body"]["thinking"] == {"type": "disabled"}
print("✓ anthropic：档位映射为 budget_tokens，且 max_tokens 始终大于预算")

# 老的布尔 enable_thinking 仍可用
assert call_ai({"ai_config": {"provider": "openai_chat", "api_key": "k", "base_url": BASE,
                              "model": "m", "enable_thinking": False}}, IMG) == ["D"]
assert "reasoning_effort" not in SEEN["body"]
print("✓ 老配置 enable_thinking=False 仍等价于关闭思考")

# --- Chat Completions
assert call_ai(cfg("openai_chat"), IMG) == ["D"]
assert SEEN["path"] == "/v1/chat/completions"
assert SEEN["body"]["messages"][0]["content"][0]["type"] == "image_url"
print("✓ openai_chat：打到 /v1/chat/completions，image_url 内联 data URI")

# --- 老配置名兼容
assert call_ai(cfg("glm"), IMG) == ["B"], "老的 provider=glm 应当仍然可用"
assert normalize_provider("codex") == "openai_responses"
print("✓ 兼容：老配置 provider=glm 仍走 Anthropic；codex 归一到 Responses")

# --- Base URL 容错：尾斜杠、用户贴了完整路径
for variant in (BASE + "/", BASE + "/v1", BASE + "/v1/messages"):
    assert call_ai(cfg("anthropic", base_url=variant), IMG) == ["B"], variant
print("✓ Base URL 容错：尾斜杠与误贴的完整路径都能纠正")

# --- 不再预填任何默认地址/模型：留空必须明确报错，而不是偷偷发到某个网关
for missing, kw in (("接口地址", {"base_url": ""}), ("模型名称", {"model": ""})):
    try:
        call_ai(cfg("anthropic", **kw), IMG); assert False
    except AIError as e:
        assert missing in str(e), e
print("✓ 地址/模型留空时明确报错，不会悄悄发往任何默认网关")

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
