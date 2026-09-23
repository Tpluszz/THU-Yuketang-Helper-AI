# -*- coding: utf-8 -*-
"""用合成的雨课堂协议报文验证 Lesson 的收题/答题逻辑（不联网）"""
import json, os, sys, tempfile, time, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOME"] = tempfile.mkdtemp()

import Scripts.Classes as C

# ---- 打桩：把所有网络调用换成可观测的假实现
POSTED = []
PPT = {
    "pres_1": {"slides": [
        {"cover": None},
        {"cover": None, "problem": {"problemId": "p1", "problemType": 1, "body": "题一",
                                    "options": [{"key": "A", "value": "a"}]}},
        {"cover": None, "problem": {"problemId": "p2", "problemType": 2, "body": "题二",
                                    "options": [{"key": "A", "value": "a"}]}},
    ]},
    "pres_2": {"slides": [
        {"cover": None, "problem": {"problemId": "p3", "problemType": 5, "body": "主观题"}},
    ]},
}

class Resp:
    def __init__(self, payload, headers=None, status=200):
        self.text = json.dumps(payload); self.status_code = status
        self.headers = headers or {}; self.content = b""

def fake_get(url, headers=None, **kw):
    pid = url.split("presentation_id=")[-1]
    return Resp({"code": 0, "data": PPT[pid]})

def fake_post(url, headers=None, data=None, **kw):
    body = json.loads(data)
    POSTED.append((url, body))
    if "checkin" in url:
        return Resp({"code": 0, "data": {"lessonToken": "tok"}}, headers={"Set-Auth": "AUTH"})
    return Resp({"code": 0, "msg": "ok"})

C.get_user_info = lambda sid: (0, {"id": 1, "name": "张三"})
C.http_get, C.http_post = fake_get, fake_post

MSGS = []
class MockUI:
    def __init__(self):
        self.config = {"sessionid": "s", "auto_answer": True,
                       "answer_config": {"answer_delay": {"type": 2, "custom": {"time": 0}},
                                         "mode": "saved"},
                       "auto_danmu": False, "danmu_config": {"danmu_limit": 5}}
    def add_message(self, m, t=0): MSGS.append((t, m))
    def on_lesson_updated(self, lesson): pass

ui = MockUI()
L = C.Lesson("L1", "测试课", "R1", ui)
ws = types.SimpleNamespace(send=lambda d: None, close=lambda: setattr(L, "_closed", True))
L.auth = L.checkin_class()
assert L.headers["Authorization"] == "Bearer AUTH", "签到未取到 Authorization"
print("✓ 签到：拿到 Set-Auth 并写入请求头")

# ---- hello：从 timeline 提取课件 + 已推送题目
L.on_message(ws, json.dumps({
    "op": "hello",
    "timeline": [{"type": "slide", "pres": "pres_1"},
                 {"type": "slide", "pres": "pres_1"},   # 重复课件
                 {"type": "problem", "prob": "p1", "limit": 30}],
}))
assert [p["problemId"] for p in L.problems_ls] == ["p1", "p2"], L.problems_ls
print("✓ hello：从 timeline 抓到 2 道题，重复课件已去重")

# 默认 saved 模式：p1 没有 answers，应只提示、不调用 AI、不提交
time.sleep(0.3)
assert any("还没有保存答案" in m for _, m in MSGS), MSGS[-3:]
assert not [u for u, b in POSTED if "problem/answer" in u], "无答案却提交了"
print("✓ 无答案的推送题目（saved 模式）：提示人工作答，未误提交")

# ---- 事先填好答案再推送，应自动提交并锁题
L.find_problem("p1")["answers"] = ["A"]
L.on_message(ws, json.dumps({"op": "unlockproblem", "problem": {"sid": "p1", "limit": 30}}))
time.sleep(0.6)
answer_posts = [b for u, b in POSTED if "problem/answer" in u]
assert answer_posts and answer_posts[-1]["problemId"] == "p1", POSTED
assert answer_posts[-1]["result"] == ["A"]
assert L.find_problem("p1")["result"] == ["A"], "提交成功后未标记 result"
print("✓ unlockproblem：自动提交答案 A，并把题目锁定为已提交")

# ---- 已提交的题再次推送应被忽略
before = len(answer_posts)
L.on_message(ws, json.dumps({"op": "unlockproblem", "problem": {"sid": "p1", "limit": 30}}))
time.sleep(0.3)
assert len([b for u, b in POSTED if "problem/answer" in u]) == before, "已答题目被重复提交"
print("✓ 重复推送同一题：已跳过，没有重复提交")

# ---- presentationupdated：增量并入新课件，且不重复已有题
L.on_message(ws, json.dumps({"op": "presentationupdated", "presentation": "pres_2"}))
L.on_message(ws, json.dumps({"op": "presentationupdated", "presentation": "pres_1"}))
assert [p["problemId"] for p in L.problems_ls] == ["p1", "p2", "p3"], L.problems_ls
print("✓ presentationupdated：新课件并入，旧题不重复")

# ---- probleminfo：按剩余时间筛选（已过期的不答）
L.find_problem("p2")["answers"] = ["A"]
now = int(time.time() * 1000)
L.on_message(ws, json.dumps({"op": "probleminfo", "problemid": "p2",
                             "limit": 10, "now": now, "dt": now - 60000}))
time.sleep(0.3)
assert L.find_problem("p2").get("result") is None, "过期题目被提交了"
print("✓ probleminfo：已过期的题目不提交")

L.on_message(ws, json.dumps({"op": "probleminfo", "problemid": "p2",
                             "limit": 60, "now": now, "dt": now - 1000}))
time.sleep(0.6)
assert L.find_problem("p2")["result"] == ["A"], "未过期题目没提交"
print("✓ probleminfo：未过期的题目正常提交")

# ---- 主观题走 {content, pics} 结构
L.find_problem("p3")["answers"] = ["我的看法"]
L.on_message(ws, json.dumps({"op": "unlockproblem", "problem": {"sid": "p3", "limit": -1}}))
time.sleep(0.6)
last = [b for u, b in POSTED if "problem/answer" in u][-1]
assert last["result"] == {"content": "我的看法", "pics": []}, last
print("✓ 主观题：按 {content, pics} 格式提交")

# ---- 下课
L.on_message(ws, json.dumps({"op": "lessonfinished"}))
assert L.finished and getattr(L, "_closed", False), "下课未关闭连接"
print("✓ lessonfinished：标记结束并关闭 websocket")

# ---- 坏报文不应让线程炸掉
L.on_message(ws, json.dumps({"op": "unlockproblem"}))
L.on_message(ws, json.dumps({"op": "probleminfo"}))
L.on_message(ws, json.dumps({"op": "没见过的op"}))
print("✓ 异常/未知报文：已捕获，不中断监听")
print("\n协议层全部通过")
