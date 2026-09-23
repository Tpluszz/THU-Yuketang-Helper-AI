# -*- coding: utf-8 -*-
"""AI 答题：统一封装不同服务商的多模态接口。

支持四种接口格式：
- anthropic         Anthropic Messages 格式（GLM、Claude 及各类兼容网关）
- openai_responses  OpenAI Responses 格式（Codex 用的就是这个）
- openai_chat       OpenAI Chat Completions 格式（最通用的第三方中转）
- qwen              阿里 dashscope 原生 SDK
"""
import base64
import json
import mimetypes
import os
import re
import time

import requests

# AI 答题的统一提示词
AI_PROMPT = ('请以JSON格式回答图片中的问题。如果是选择题，则返回'
             '{"question": "问题", "answer": ["选项（A/B/C/...）"]}，选项为圆形则为单选，选项为矩形则为多选；'
             '如果是填空题，则返回{"question": "问题", "answer": ["填空1答案", "填空2答案", ...]}；'
             '如果是主观题，则返回{"question": "问题", "answer": ["主观题答案"]}')

# 复核提示词：把候选答案连同原图一起发回去，让模型自查一遍
REVIEW_PROMPT = ('请复核图片中这道题的答案。候选答案是：%s\n'
                 '如果候选答案正确，返回 {"ok": true, "answer": [候选答案]}；'
                 '如果不正确，返回 {"ok": false, "answer": [你认为正确的答案], "reason": "一句话说明理由"}。'
                 '答案格式与原题一致（选择题用 A/B/C/... ，填空题按空的顺序给出）。只返回 JSON。')

# 各接口格式的元信息，UI 直接读这里渲染。
# 注意：base_url / model 一律不预填默认值——预填一个陌生网关等于把用户的
# API Key 默认发到第三方服务器上。示例只作为输入框下方的灰字提示。
PROVIDERS = {
    "anthropic": {
        "label": "Anthropic 格式（Claude / GLM / 兼容网关）",
        "path": "/v1/messages",
        "needs_url": True,
        "url_example": "https://api.anthropic.com",
        "model_example": "claude-sonnet-5 / glm-5.3-flash",
        "reasoning": "anthropic",
    },
    "openai_responses": {
        "label": "OpenAI Responses 格式（Codex）",
        "path": "/v1/responses",
        "needs_url": True,
        "url_example": "https://api.openai.com",
        "model_example": "gpt-5.1-codex",
        "reasoning": "effort",
    },
    "openai_chat": {
        "label": "OpenAI Chat Completions 格式",
        "path": "/v1/chat/completions",
        "needs_url": True,
        "url_example": "https://api.openai.com",
        "model_example": "gpt-4o",
        "reasoning": "effort",
    },
    "qwen": {
        "label": "通义千问 Qwen（dashscope SDK）",
        "path": "",
        "needs_url": False,
        "url_example": "",
        "model_example": "qwen-vl-max-latest",
        "reasoning": "none",
    },
}

# 思考强度档位。
# Anthropic：budget_tokens 已废弃——在 Opus 4.6/Sonnet 4.6 上弃用，在 Fable 5/5.1、
#   Opus 5/4.8/4.7、Sonnet 5 上直接 400。现在用 thinking:{type:"adaptive"} 打开思考，
#   深度由 output_config.effort 控制，取值 low/medium/high/xhigh/max。
#   老网关（部分 GLM 兼容实现）只认旧的 budget_tokens，被拒时会自动回退一次。
# OpenAI：reasoning.effort / reasoning_effort 取 minimal/low/medium/high(/xhigh)，
#   xhigh 能否用取决于模型（gpt-5.1-codex-max、gpt-5.3-codex 支持）。
EFFORT_LABELS = {
    "off":     "关闭",
    "minimal": "最低",
    "low":     "低",
    "medium":  "中",
    "high":    "高",
    "xhigh":   "极高",
    "max":     "最高",
}
EFFORTS = tuple(EFFORT_LABELS)
# 各家 API 形状上就不存在的档位，做一次无损靠拢（与「模型是否支持」无关）
CLAMP_ANTHROPIC = {"minimal": "low"}                 # Anthropic effort 无 minimal
CLAMP_OPENAI = {"max": "xhigh"}                      # OpenAI 无 max
# 老网关回退用的思考预算
LEGACY_BUDGET = {"minimal": 1024, "low": 2048, "medium": 8192,
                 "high": 16384, "xhigh": 24576, "max": 32768}

# 老配置里的 provider 名
ALIASES = {"glm": "anthropic", "openai": "openai_chat", "codex": "openai_responses"}

DEFAULT_PROVIDER = "anthropic"
DEFAULT_BASE_URL = ""       # 故意留空：必须由用户显式填写
DEFAULT_MODEL = ""

RETRYABLE = (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
MAX_RETRY = 2
TIMEOUT = 180


class AIError(Exception):
    """AI 调用失败，消息可直接展示给用户。"""


def normalize_provider(name):
    """把别名和历史值归一到当前的 provider 键。"""
    name = (name or DEFAULT_PROVIDER).strip()
    name = ALIASES.get(name, name)
    return name if name in PROVIDERS else DEFAULT_PROVIDER


def provider_defaults(name):
    return PROVIDERS[normalize_provider(name)]


# ---------------------------------------------------------------- 解析

def _extract_json(text):
    """从 AI 返回的文本中提取 JSON 对象。

    兼容 markdown 代码块、双大括号，以及 JSON 之后附带解析文字的情况。
    """
    text = (text or "").strip()
    if not text:
        raise AIError("AI 未返回文本内容（可能思考过程耗尽了输出长度限制，可尝试关闭思考模式）")
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    text = text.replace("{{", "{").replace("}}", "}")
    start = text.find("{")
    if start == -1:
        raise AIError("AI 返回内容中没有 JSON 对象：%s" % text[:120])
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise AIError("AI 返回的 JSON 无法解析：%s" % text[start:start + 120]) from exc
    return obj


def _normalize_answer(raw):
    """把各种形态的 answer 统一成字符串列表。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        stripped = raw.strip()
        # "AB" 这种连写的多选答案拆开
        if len(stripped) > 1 and all(ch in "ABCDEFGH" for ch in stripped):
            return list(stripped)
        return [stripped]
    if isinstance(raw, (list, tuple)):
        out = []
        for item in raw:
            out.extend(_normalize_answer(item))
        return out
    return [str(raw)]


def _image_data_uri(image_path):
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    media_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    return media_type, data


# ---------------------------------------------------------------- 传输

def _post(url, headers, body, timeout=TIMEOUT):
    """带退避重试地发一个 JSON 请求，并把常见状态码翻成人话。"""
    last = None
    for attempt in range(MAX_RETRY + 1):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=timeout,
                              proxies={"http": None, "https": None})
            break
        except RETRYABLE as exc:
            last = exc
            if attempt < MAX_RETRY:
                time.sleep(1.5 * (attempt + 1))
    else:
        raise AIError("网络连接失败：%s" % last)

    if r.status_code in (401, 403):
        raise AIError("API Key 无效或没有权限（HTTP %s）" % r.status_code)
    if r.status_code == 404:
        raise AIError("接口地址不对（HTTP 404）：%s\n请检查 Base URL 与所选接口格式是否匹配" % url)
    if r.status_code == 429:
        raise AIError("请求过于频繁，已被限流（HTTP 429），可在设置中调低并发数")
    if r.status_code == 400:
        detail = r.text[:400]
        low = detail.lower()
        if any(k in low for k in ("reasoning", "effort", "thinking", "budget")):
            raise AIError("当前模型不支持所选的思考强度：%s\n"
                          "请在「设置 → AI 服务」里把思考强度调低一档再试。" % detail)
        raise AIError("请求被拒绝（HTTP 400）：%s" % detail)
    if r.status_code != 200:
        raise AIError("接口返回状态码 %s：%s" % (r.status_code, r.text[:300]))
    try:
        return r.json()
    except ValueError:
        raise AIError("接口返回的不是 JSON：%s" % r.text[:200])


def _looks_like_thinking_error(exc):
    text = str(exc).lower()
    return any(k in text for k in ("thinking", "adaptive", "budget_tokens",
                                   "output_config", "effort"))


def _require_model(model):
    model = (model or "").strip()
    if not model:
        raise AIError("请先在「设置 → AI 服务」里填写模型名称"
                      "（可点「获取模型列表」从服务端拉取）")
    return model


def _base(base_url, provider):
    """归一化 Base URL：必须由用户提供，顺带容忍用户把完整路径贴进来。"""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise AIError("请先在「设置 → AI 服务」里填写接口地址（Base URL）")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # 用户可能直接贴了 .../v1/messages 这种完整地址，去掉重复的尾巴
    for suffix in ("/v1/messages", "/v1/responses", "/v1/chat/completions", "/v1"):
        if url.endswith(suffix):
            url = url[:-len(suffix)]
            break
    return url.rstrip("/")


def normalize_effort(value, provider=None):
    """把配置里的思考强度归一；兼容老的布尔 enable_thinking。"""
    if isinstance(value, bool):
        value = "medium" if value else "off"
    value = (value or "").strip().lower()
    if value not in EFFORTS:
        value = "medium"
    if provider and PROVIDERS[normalize_provider(provider)]["reasoning"] == "none":
        return "off"
    return value


def effort_hint(provider, effort):
    """这一档在当前格式下实际发出去的是什么，用于界面上直说。"""
    provider = normalize_provider(provider)
    effort = normalize_effort(effort, provider)
    kind = PROVIDERS[provider]["reasoning"]
    if kind == "none":
        return "该接口不支持思考强度"
    if effort == "off":
        return "不发送思考参数" if kind == "effort" else "thinking.type = disabled"
    if kind == "anthropic":
        return "thinking=adaptive，output_config.effort = %s" % CLAMP_ANTHROPIC.get(effort, effort)
    field = "reasoning.effort" if provider == "openai_responses" else "reasoning_effort"
    return "%s = %s" % (field, CLAMP_OPENAI.get(effort, effort))


def resolve_effort(ai_config):
    """从 ai_config 取出思考强度，优先读新键，并按 provider 收敛到可用档。"""
    ai_config = ai_config or {}
    provider = normalize_provider(ai_config.get("provider"))
    raw = (ai_config.get("thinking_effort") if "thinking_effort" in ai_config
           else ai_config.get("enable_thinking", True))
    return normalize_effort(raw, provider)


# ---------------------------------------------------------------- 各家实现

def call_anthropic(api_key, image_path, prompt, base_url, model, effort="medium"):
    """Anthropic Messages 格式：POST /v1/messages"""
    headers = {
        "Authorization": "Bearer %s" % api_key,
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    content = []
    if image_path and os.path.exists(image_path):
        media_type, data = _image_data_uri(image_path)
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": data}})
    content.append({"type": "text", "text": prompt})
    effort = CLAMP_ANTHROPIC.get(normalize_effort(effort, "anthropic"),
                                 normalize_effort(effort, "anthropic"))
    url = _base(base_url, "anthropic") + "/v1/messages"
    body = {
        "model": _require_model(model),
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": content}],
    }
    if effort == "off":
        body["thinking"] = {"type": "disabled"}
    else:
        body["thinking"] = {"type": "adaptive"}
        body["output_config"] = {"effort": effort}

    try:
        result = _post(url, headers, body)
    except AIError as exc:
        # 部分老网关只认早已废弃的 budget_tokens 写法，被拒时回退一次再试
        if effort == "off" or not _looks_like_thinking_error(exc):
            raise
        legacy = dict(body)
        legacy.pop("output_config", None)
        budget = LEGACY_BUDGET[effort]
        legacy["thinking"] = {"type": "enabled", "budget_tokens": budget}
        legacy["max_tokens"] = budget + 2048     # max_tokens 必须大于思考预算
        result = _post(url, headers, legacy)
    text = "".join(b.get("text", "") for b in result.get("content", []) if b.get("type") != "thinking")
    return _normalize_answer(_extract_json(text).get("answer"))


def call_openai_responses(api_key, image_path, prompt, base_url, model, effort="medium"):
    """OpenAI Responses 格式：POST /v1/responses（Codex 使用）"""
    headers = {"Authorization": "Bearer %s" % api_key, "content-type": "application/json"}
    content = []
    if image_path and os.path.exists(image_path):
        media_type, data = _image_data_uri(image_path)
        content.append({"type": "input_image",
                        "image_url": "data:%s;base64,%s" % (media_type, data)})
    content.append({"type": "input_text", "text": prompt})
    effort = normalize_effort(effort, "openai_responses")
    effort = CLAMP_OPENAI.get(effort, effort)
    body = {
        "model": _require_model(model),
        "input": [{"role": "user", "content": content}],
        "max_output_tokens": 8192 if effort in ("high", "xhigh") else 4096,
    }
    # 非推理模型不认 reasoning 字段，所以「关闭」时干脆不发
    if effort != "off":
        body["reasoning"] = {"effort": effort}

    result = _post(_base(base_url, "openai_responses") + "/v1/responses", headers, body)
    return _normalize_answer(_extract_json(_responses_text(result)).get("answer"))


def _responses_text(result):
    """从 Responses API 的返回里取出正文，跳过 reasoning 条目。"""
    # 部分实现直接给了聚合好的 output_text
    if isinstance(result.get("output_text"), str) and result["output_text"].strip():
        return result["output_text"]
    parts = []
    for item in result.get("output", []):
        if item.get("type") == "reasoning":
            continue
        for block in item.get("content", []) or []:
            if block.get("type") in ("output_text", "text") and block.get("text"):
                parts.append(block["text"])
    if not parts and result.get("status") == "incomplete":
        raise AIError("模型输出被截断（%s），可尝试关闭思考模式"
                      % (result.get("incomplete_details", {}).get("reason", "incomplete")))
    return "".join(parts)


def call_openai_chat(api_key, image_path, prompt, base_url, model, effort="medium"):
    """OpenAI Chat Completions 格式：POST /v1/chat/completions"""
    headers = {"Authorization": "Bearer %s" % api_key, "content-type": "application/json"}
    content = []
    if image_path and os.path.exists(image_path):
        media_type, data = _image_data_uri(image_path)
        content.append({"type": "image_url",
                        "image_url": {"url": "data:%s;base64,%s" % (media_type, data)}})
    content.append({"type": "text", "text": prompt})
    effort = normalize_effort(effort, "openai_chat")
    effort = CLAMP_OPENAI.get(effort, effort)
    body = {
        "model": _require_model(model),
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4096,
    }
    if effort != "off":
        # o 系列等推理模型认这个字段，普通模型的服务端会忽略
        body["reasoning_effort"] = effort
    result = _post(_base(base_url, "openai_chat") + "/v1/chat/completions", headers, body)
    choices = result.get("choices") or []
    if not choices:
        raise AIError("接口没有返回 choices：%s" % str(result)[:200])
    message = choices[0].get("message") or {}
    text = message.get("content")
    if isinstance(text, list):      # 少数实现把 content 也返回成块数组
        text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
    return _normalize_answer(_extract_json(text).get("answer"))


def call_qwen(api_key, image_path, prompt, base_url=None, model=None, effort="off"):
    """阿里 dashscope 原生 SDK。"""
    try:
        from dashscope import MultiModalConversation
    except ImportError:
        raise AIError("未安装 dashscope，使用通义千问请先执行：pip install dashscope")
    messages = [
        {"role": "system", "content": [{"text": "You are a helpful assistant."}]},
        {"role": "user", "content": [
            {"image": "file://%s" % os.path.abspath(image_path)},
            {"text": prompt},
        ]},
    ]
    response = MultiModalConversation.call(
        api_key=api_key,
        model=model or "qwen-vl-max-latest",
        messages=messages,
        response_format={"type": "json_object"},
        vl_high_resolution_images=True)
    try:
        json_output = response["output"]["choices"][0]["message"].content[0]["text"]
    except (KeyError, IndexError, TypeError):
        raise AIError("通义千问返回格式异常：%s" % str(response)[:200])
    return _normalize_answer(_extract_json(json_output).get("answer"))


DISPATCH = {
    "anthropic": call_anthropic,
    "openai_responses": call_openai_responses,
    "openai_chat": call_openai_chat,
    "qwen": call_qwen,
}

# 兼容老代码里的名字
call_glm = call_anthropic


# ---------------------------------------------------------------- 入口

def call_ai(config, image_path, prompt=AI_PROMPT):
    """根据配置中的 ai_config 选择接口格式并返回 answer 列表。"""
    ai_config = (config or {}).get("ai_config", {})
    provider = normalize_provider(ai_config.get("provider"))
    api_key = (ai_config.get("api_key") or "").strip()
    if not api_key:
        raise AIError("未配置 AI API Key，请先在「设置」中填写")
    if not image_path or not os.path.exists(image_path):
        raise AIError("题目截图缺失，无法调用 AI（可尝试重新进入课程以重新下载）")
    return DISPATCH[provider](
        api_key, image_path, prompt,
        base_url=ai_config.get("base_url"),
        model=ai_config.get("model"),
        effort=resolve_effort(ai_config))


def review_answer(config, image_path, answers):
    """让 AI 复核一遍候选答案。

    返回 (最终答案, 是否被改过)。复核只是加一道保险，
    调用方负责在它失败时沿用原答案，而不是把整次作答弄丢。
    """
    original = [str(a) for a in (answers or [])]
    if not original:
        return original, False
    shown = "、".join(original)
    reviewed = call_ai(config, image_path, REVIEW_PROMPT % shown) or original
    reviewed = [str(a) for a in reviewed]
    changed = [a.strip() for a in reviewed] != [a.strip() for a in original]
    return reviewed, changed


def list_models(ai_config):
    """GET {Base URL}/v1/models，返回模型 id 列表，供设置页下拉选择。"""
    provider = normalize_provider(ai_config.get("provider"))
    if provider == "qwen":
        # dashscope 没有公开的列表接口，给出常用的多模态模型
        return ["qwen-vl-max-latest", "qwen-vl-max", "qwen-vl-plus"]
    api_key = (ai_config.get("api_key") or "").strip()
    if not api_key:
        raise AIError("请先填写 API Key")
    url = _base(ai_config.get("base_url"), provider) + "/v1/models"
    headers = {"Authorization": "Bearer %s" % api_key, "x-api-key": api_key,
               "anthropic-version": "2023-06-01"}
    try:
        r = requests.get(url, headers=headers, timeout=30,
                         proxies={"http": None, "https": None})
    except requests.exceptions.RequestException as exc:
        raise AIError("无法连接 %s：%s" % (url, exc))
    if r.status_code in (401, 403):
        raise AIError("API Key 无效或没有权限（HTTP %s）" % r.status_code)
    if r.status_code == 404:
        raise AIError("该服务不提供模型列表接口（HTTP 404），请手动填写模型名")
    if r.status_code != 200:
        raise AIError("获取模型列表失败（HTTP %s）：%s" % (r.status_code, r.text[:200]))
    try:
        payload = r.json()
    except ValueError:
        raise AIError("模型列表返回的不是 JSON：%s" % r.text[:200])
    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise AIError("看不懂的模型列表格式：%s" % str(payload)[:200])
    models = []
    for item in items:
        name = item.get("id") or item.get("name") if isinstance(item, dict) else item
        if name:
            models.append(str(name))
    if not models:
        raise AIError("服务端返回了空的模型列表")
    return sorted(set(models))


def test_connection(ai_config):
    """用一条极短的纯文本请求验证配置是否可用，返回提示文案。"""
    api_key = (ai_config.get("api_key") or "").strip()
    if not api_key:
        raise AIError("请先填写 API Key")
    provider = normalize_provider(ai_config.get("provider"))
    model = _require_model(ai_config.get("model"))

    if provider == "qwen":
        try:
            from dashscope import MultiModalConversation  # noqa: F401
        except ImportError:
            raise AIError("未安装 dashscope，使用通义千问请先执行：pip install dashscope")
        return "dashscope 已安装，Key 将在首次答题时校验"

    base = _base(ai_config.get("base_url"), provider)
    if provider == "anthropic":
        url = base + "/v1/messages"
        headers = {"Authorization": "Bearer %s" % api_key, "x-api-key": api_key,
                   "anthropic-version": "2023-06-01", "content-type": "application/json"}
        # 连通性测试不带任何 thinking 参数，避免新老网关写法差异干扰判断
        body = {"model": model, "max_tokens": 64,
                "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]}
    elif provider == "openai_responses":
        url = base + "/v1/responses"
        headers = {"Authorization": "Bearer %s" % api_key, "content-type": "application/json"}
        body = {"model": model, "max_output_tokens": 16,
                "input": [{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}]}
    else:
        url = base + "/v1/chat/completions"
        headers = {"Authorization": "Bearer %s" % api_key, "content-type": "application/json"}
        body = {"model": model, "max_tokens": 16,
                "messages": [{"role": "user", "content": "hi"}]}

    _post(url, headers, body, timeout=30)
    return "连接成功，模型 %s 可用" % model
