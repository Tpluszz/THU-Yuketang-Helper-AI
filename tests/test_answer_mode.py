# -*- coding: utf-8 -*-
"""验证「课上推送新题目时」四种模式的行为差异"""
import json, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOME"] = tempfile.mkdtemp()

import Scripts.Classes as C
from Scripts.Utils import migrate_answer_mode

class Resp:
    def __init__(s, payload, headers=None):
        s.text = json.dumps(payload); s.status_code = 200
        s.headers = headers or {}; s.content = b""

POSTED = []
def fake_post(url, headers=None, data=None, **kw):
    POSTED.append(url)
    if "checkin" in url:
        return Resp({"code": 0, "data": {"lessonToken": "t"}}, {"Set-Auth": "A"})
    return Resp({"code": 0})
C.get_user_info = lambda s: (0, {"id": 1, "name": "张三"})
C.http_post = fake_post
C.http_get = lambda *a, **k: Resp({"code": 0, "data": {"slides": []}})

AI_CALLS = []
C.call_ai = lambda cfg, img, prompt=None: (AI_CALLS.append(img), ["A"])[1]

MSGS = []
class UIm:
    """带 confirm_answer 的假 UI；decision 决定用户点同意还是拒绝。"""
    def __init__(self, mode, decision=True, respond=True):
        self.config = {"sessionid": "s", "auto_danmu": False,
                       "answer_config": {"answer_delay": {"type": 2, "custom": {"time": 0}},
                                         "mode": mode, "confirm_timeout": 2},
                       "ai_config": {"api_key": "k", "provider": "anthropic"}}
        self.decision, self.respond = decision, respond
        self.asked = []
    def add_message(self, m, t=0): MSGS.append(m)
    def on_lesson_updated(self, l): pass
    def confirm_answer(self, lesson, problem, answers, timeout, on_decided):
        self.asked.append((answers, timeout))
        if self.respond:
            on_decided(self.decision)

def run(mode, preset_answer=False, **kw):
    POSTED.clear(); AI_CALLS.clear(); MSGS.clear()
    ui = UIm(mode, **kw)
    L = C.Lesson("L", "课", "R", ui)
    L.problems_ls = [{"problemId": "p", "problemType": 1, "page": 3, "body": "Q",
                      "options": [{"key": "A", "value": "a"}],
                      "answers": ["A"] if preset_answer else [], "image": __file__}]
    L.handle_pushed_problem("p", 30)
    time.sleep(0.6)
    return (any("problem/answer" in u for u in POSTED), len(AI_CALLS), L.problems_ls[0], ui)

# 1) notify
sub, ai, prob, _ = run("notify")
assert not sub and ai == 0 and not prob["answers"]
assert any("请自行前往雨课堂作答" in m for m in MSGS), MSGS
print("✓ notify：不调用 AI、不提交，只提示")

# 2) saved 有答案
sub, ai, prob, _ = run("saved", preset_answer=True)
assert sub and ai == 0 and prob.get("result") == ["A"]
print("✓ saved（已有答案）：直接提交，不调用 AI")

# 3) saved 无答案 —— 绝不偷偷用 AI
sub, ai, prob, _ = run("saved")
assert not sub and ai == 0
assert any("还没有保存答案" in m for m in MSGS), MSGS
print("✓ saved（无答案）：不偷偷调用 AI，只提醒")

# 4) ai_confirm 同意 → 提交
sub, ai, prob, ui = run("ai_confirm", decision=True)
assert ai == 1 and ui.asked and ui.asked[0][0] == ["A"]
assert sub and prob.get("result") == ["A"]
print("✓ ai_confirm（点同意）：弹确认框，同意后提交")

# 5) ai_confirm 拒绝 → 不提交但答案保留  ← 你要的「不自动提交」
sub, ai, prob, ui = run("ai_confirm", decision=False)
assert ai == 1 and ui.asked
assert not sub, "⚠️ 拒绝了竟然还提交"
assert prob.get("result") is None, "不应被标记为已提交"
assert prob["answers"] == ["A"], "拒绝后答案应保留，方便手动提交"
assert any("未确认" in m for m in MSGS), MSGS
print("✓ ai_confirm（点拒绝）：不提交，答案保留在题目里可手动处理")

# 6) ai_confirm 超时无人应答 → 保守不提交
sub, ai, prob, ui = run("ai_confirm", respond=False)
assert not sub and prob.get("result") is None
print("✓ ai_confirm（超时无响应）：保守处理，不提交")

# 7) 确认框超时受剩余答题时间限制
_, _, _, ui = run("ai_confirm", decision=True)
assert ui.asked[0][1] <= 27, "超时应被剩余时间(30s)减去余量压到 27s 以内，实际 %s" % ui.asked[0][1]
print("✓ ai_confirm：确认等待时间被题目剩余时间压制（%ss）" % ui.asked[0][1])

# 8) ai_auto
sub, ai, prob, ui = run("ai_auto")
assert ai == 1 and sub and prob.get("result") == ["A"] and not ui.asked
print("✓ ai_auto：调用 AI 后直接提交，不弹窗")

# 9) 老配置迁移
for old, want in ((({"auto_answer": False}), "notify"),
                  ({"auto_answer": True, "answer_config": {"auto_ai": False}}, "saved"),
                  ({"auto_answer": True, "answer_config": {"auto_ai": True}}, "ai_auto")):
    got = migrate_answer_mode(dict(old))["answer_config"]["mode"]
    assert got == want, (old, got, want)
print("✓ 老配置 auto_answer/auto_ai 正确折算为 notify / saved / ai_auto")
print("\n四种答题模式全部通过")
