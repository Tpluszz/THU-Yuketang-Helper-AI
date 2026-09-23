# -*- coding: utf-8 -*-
"""AI 答题：统一封装不同服务商的多模态接口。"""
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

PROVIDERS = {
    "glm": "GLM / Anthropic 兼容接口",
    "qwen": "通义千问 Qwen（dashscope）",
}

DEFAULT_BASE_URL = "https://sec.llm.autos"
DEFAULT_MODEL = "glm-5.3-flash"

# 网络抖动、限流等临时故障值得重试
RETRYABLE = (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
MAX_RETRY = 2


class AIError(Exception):
    """AI 调用失败，消息可直接展示给用户。"""


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
    # 模型可能模仿提示词中的双大括号格式
    text = text.replace("{{", "{").replace("}}", "}")
    start = text.find("{")
    if start == -1:
        raise AIError("AI 返回内容中没有 JSON 对象：%s" % text[:120])
    try:
        # 解析第一个完整 JSON 对象，忽略其后的说明文字
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise AIError("AI 返回的 JSON 无法解析：%s" % text[start:start + 120]) from exc
    return obj


def _normalize_answer(raw):
    """把各种形态的 answer 统一成字符串列表。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        # "AB" 这种连写的多选答案拆开
        stripped = raw.strip()
        if len(stripped) > 1 and all(ch in "ABCDEFGH" for ch in stripped):
            return list(stripped)
        return [stripped]
    if isinstance(raw, (list, tuple)):
        out = []
        for item in raw:
            out.extend(_normalize_answer(item))
        return out
    return [str(raw)]


def _image_to_base64_block(image_path):
    """将本地图片转成 Anthropic 消息格式的 base64 块。"""
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    media_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def _with_retry(func):
    """对临时性网络故障做有限次退避重试。"""
    last = None
    for attempt in range(MAX_RETRY + 1):
        try:
            return func()
        except RETRYABLE as exc:
            last = exc
            if attempt < MAX_RETRY:
                time.sleep(1.5 * (attempt + 1))
    raise AIError("网络连接失败：%s" % last)


def call_glm(api_key, image_path, prompt, base_url, model, enable_thinking=True):
    """调用 Anthropic 兼容接口（如 GLM），返回 answer 列表。"""
    url = (base_url or DEFAULT_BASE_URL).rstrip("/") + "/v1/messages"
    headers = {
        "Authorization": "Bearer %s" % api_key,
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    content = []
    if image_path and os.path.exists(image_path):
        content.append(_image_to_base64_block(image_path))
    content.append({"type": "text", "text": prompt})
    body = {
        "model": model or DEFAULT_MODEL,
        # thinking 模型需要较大的输出空间，避免思考过程耗尽 token 后没有正文
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": content}],
    }
    if not enable_thinking:
        body["thinking"] = {"type": "disabled"}

    def _do():
        return requests.post(url, headers=headers, json=body, timeout=180,
                             proxies={"http": None, "https": None})

    r = _with_retry(_do)
    if r.status_code == 401 or r.status_code == 403:
        raise AIError("API Key 无效或没有权限（HTTP %s）" % r.status_code)
    if r.status_code == 429:
        raise AIError("请求过于频繁，已被限流（HTTP 429），可在设置中调低并发数")
    if r.status_code != 200:
        raise AIError("接口返回状态码 %s：%s" % (r.status_code, r.text[:300]))
    try:
        result = r.json()
    except ValueError:
        raise AIError("接口返回的不是 JSON：%s" % r.text[:200])
    text = "".join(block.get("text", "") for block in result.get("content", []))
    return _normalize_answer(_extract_json(text).get("answer"))


def call_qwen(api_key, image_path, prompt):
    """调用阿里 dashscope 的 qwen-vl 接口，返回 answer 列表。"""
    try:
        from dashscope import MultiModalConversation
    except ImportError:
        raise AIError("未安装 dashscope，使用通义千问请先执行：pip install dashscope")
    messages = [
        {"role": "system", "content": [{"text": "You are a helpful assistant."}]},
        {
            "role": "user",
            "content": [
                {"image": "file://%s" % os.path.abspath(image_path)},
                {"text": prompt},
            ],
        },
    ]
    response = MultiModalConversation.call(
        api_key=api_key,
        model="qwen-vl-max-latest",
        messages=messages,
        response_format={"type": "json_object"},
        vl_high_resolution_images=True)
    try:
        json_output = response["output"]["choices"][0]["message"].content[0]["text"]
    except (KeyError, IndexError, TypeError):
        raise AIError("通义千问返回格式异常：%s" % str(response)[:200])
    return _normalize_answer(_extract_json(json_output).get("answer"))


def call_ai(config, image_path, prompt=AI_PROMPT):
    """根据配置中的 ai_config 选择 AI 服务并返回 answer 列表。"""
    ai_config = (config or {}).get("ai_config", {})
    provider = ai_config.get("provider", "glm")
    api_key = (ai_config.get("api_key") or "").strip()
    if not api_key:
        raise AIError("未配置 AI API Key，请先在「设置」中填写")
    if not image_path or not os.path.exists(image_path):
        raise AIError("题目截图缺失，无法调用 AI（可尝试重新进入课程以重新下载）")
    if provider == "qwen":
        return call_qwen(api_key, image_path, prompt)
    return call_glm(api_key, image_path, prompt,
                    base_url=ai_config.get("base_url", DEFAULT_BASE_URL),
                    model=ai_config.get("model", DEFAULT_MODEL),
                    enable_thinking=ai_config.get("enable_thinking", True))


def test_connection(ai_config):
    """用一条极短的纯文本请求验证配置是否可用，返回提示文案。"""
    api_key = (ai_config.get("api_key") or "").strip()
    if not api_key:
        raise AIError("请先填写 API Key")
    provider = ai_config.get("provider", "glm")
    if provider == "qwen":
        try:
            from dashscope import MultiModalConversation  # noqa: F401
        except ImportError:
            raise AIError("未安装 dashscope，使用通义千问请先执行：pip install dashscope")
        return "dashscope 已安装，Key 将在首次答题时校验"

    url = (ai_config.get("base_url") or DEFAULT_BASE_URL).rstrip("/") + "/v1/messages"
    headers = {
        "Authorization": "Bearer %s" % api_key,
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": ai_config.get("model") or DEFAULT_MODEL,
        "max_tokens": 16,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        "thinking": {"type": "disabled"},
    }
    try:
        r = requests.post(url, headers=headers, json=body, timeout=30,
                          proxies={"http": None, "https": None})
    except requests.exceptions.RequestException as exc:
        raise AIError("无法连接接口地址：%s" % exc)
    if r.status_code in (401, 403):
        raise AIError("API Key 无效或没有权限（HTTP %s）" % r.status_code)
    if r.status_code != 200:
        raise AIError("接口返回状态码 %s：%s" % (r.status_code, r.text[:200]))
    return "连接成功，模型 %s 可用" % (ai_config.get("model") or DEFAULT_MODEL)
