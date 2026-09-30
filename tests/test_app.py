# -*- coding: utf-8 -*-
"""控制器 App：界面调用的每个接口都在这里过一遍（不联网、不依赖界面）"""
import json, os, sys, tempfile, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOME"] = tempfile.mkdtemp()

import Scripts.Notify as N
N.system_notify = lambda t, m: True
N.play_sound = lambda urgent=False: None

import Scripts.AI as AI
import Scripts.App as A
import Scripts.Classes as C

EVENTS = []
def emit(event, data):
    EVENTS.append((event, data))
def events(name):
    return [d for e, d in EVENTS if e == name]

app = A.App(emit=emit)

# ------------------------------------------------ 启动与状态
boot = app.bootstrap()
assert set(boot) == {"state", "lessons", "logs", "meta"}
assert len(boot["meta"]["providers"]) == 4 and len(boot["meta"]["modes"]) == 4
assert boot["state"]["ai"]["ready"] is False
print("✓ bootstrap：状态、课程、日志、元信息齐全；未配置 AI 时 ready=False")

app.refresh_login()
assert app.login_state == "none" and events("state")[-1]["login"]["state"] == "none"
r = app.start_monitor()
assert r["ok"] is False and "登录" in r["error"]
print("✓ 未登录：状态为 none，启动监听被拒并说明原因")

# ------------------------------------------------ 测试模式
r = app.enter_test_mode()
LID = r["lessonId"]
lessons = events("lessons")[-1]
assert lessons[0]["status"] == "test" and lessons[0]["problemCount"] == 5
assert lessons[0]["slides"] == 5
print("✓ 测试模式：课程列表出现示例课程（5 题、5 页课件）")

d = app.lesson_detail(LID)
widgets = [p["widget"] for p in d["problems"]]
assert widgets == ["single", "multi", "blanks", "text", "single"], widgets
assert d["problems"][4]["submitted"] is True and d["problems"][2]["blanks"] == 2
print("✓ 题目详情：单选/多选/填空(2空)/主观/已提交 五种控件判定正确")

uri = app.problem_image(LID, d["problems"][0]["id"], 300)
assert uri.startswith("data:image/jpeg;base64,") and len(uri) < 60000
assert app.problem_image(LID, d["problems"][0]["id"], 300) is uri
print("✓ 截图：缩放为 data URI 并缓存（%.0f KB）" % (len(uri) / 1024))

# ------------------------------------------------ 作答
P0, P1, P4 = (d["problems"][i]["id"] for i in (0, 1, 4))
r = app.save_answer(LID, P0, ["B"])
assert r["ok"] and r["problem"]["answers"] == ["B"] and not r["problem"]["submitted"]
r = app.save_answer(LID, P4, ["A"])
assert r["ok"] is False and "提交过" in r["error"]
print("✓ 保存答案；已提交的题拒绝修改")

r = app.submit_answer(LID, P0, [])
assert r["ok"] is False
r = app.submit_answer(LID, P0, ["B"])
assert r["ok"] and r["problem"]["submitted"]
print("✓ 提交：空答案被拒；测试课程模拟提交后锁定")

# ------------------------------------------------ AI（打桩）
app.config["ai_config"].update(api_key="k", base_url="http://x", model="m")
calls = []
AI.call_ai = lambda cfg, img, prompt=None, timeout=None: (calls.append(img), ["A", "C"])[1]
AI.explain_problem = lambda cfg, img, timeout=None: {"answer": ["A"], "explanation": "考点是……"}
AI.review_answer = lambda cfg, img, ans, timeout=None: {
    "ok": False, "answer": ["A", "B"], "changed": True, "reason": "漏了 B"}

r = app.ai_solve(LID, P1)
assert r["ok"] and r["answers"] == ["A", "C"] and r["problem"]["answers"] == ["A", "C"]
r = app.ai_explain(LID, P1)
assert r["ok"] and r["explanation"] == "考点是……"
assert r["problem"]["answers"] == ["A", "C"], "已有答案时讲解不应覆盖用户答案"
r = app.ai_review(LID, P1, ["A", "C"])
assert r["ok"] and r["agreed"] is False and r["answer"] == ["A", "B"] and r["reason"] == "漏了 B"
assert app.lesson_detail(LID)["problems"][1]["review"]["reason"] == "漏了 B"
print("✓ AI 解答 / 讲解（不覆盖已有答案）/ 复核（返回理由并存档）")

app.config["ai_config"]["api_key"] = ""
r = app.ai_solve(LID, P1)
assert r["ok"] is False and "AI 还没配置好" in r["error"]
app.config["ai_config"]["api_key"] = "k"
print("✓ AI 未配置时给出去哪配置的提示")

# ------------------------------------------------ 批量解题
EVENTS.clear()
def slow(cfg, img, prompt=None, timeout=None):
    time.sleep(0.15); return ["D"]
AI.call_ai = slow
r = app.solve_all(LID)
assert r["ok"] and r["total"] == 2, r       # 第 3、4 题还没答案
assert app.solve_all(LID)["ok"] is False    # 重复发起被拒
deadline = time.time() + 5
while time.time() < deadline and not (events("batch") and events("batch")[-1]["finished"]):
    time.sleep(0.05)
last = events("batch")[-1]
assert last["finished"] and last["ok"] == 2 and last["done"] == 2, last
print("✓ 批量解题：只解没答案的题、不能重复发起、进度事件完整")

# ------------------------------------------------ 确认流程
EVENTS.clear()
decided = []
lesson = app.get_lesson(LID)
prob = lesson.find_problem(d["problems"][0]["id"])
prob.pop("result", None)
app.confirm_answer(lesson, prob, ["B"], 30, decided.append)
ev = events("confirm")[-1]
assert ev["answers"] == ["B"] and ev["problem"]["image"].startswith("data:image")
assert events("toast")[-1]["urgent"] is True
r = app.confirm_decide(ev["token"], True, answers=["C"])
assert r["ok"] and decided == [True] and prob["answers"] == ["C"]
assert app.confirm_decide(ev["token"], True)["ok"] is False
print("✓ 确认：推送带截图的确认请求 + 紧急提醒；可在确认框里改答案；重复决定被拒")

app.confirm_answer(lesson, prob, ["B"], 1, decided.append)
tok = events("confirm")[-1]["token"]
time.sleep(2.3)
assert any(c.get("expired") and c["token"] == tok for c in events("confirm_closed"))
print("✓ 确认超时：界面收到关闭通知")

# ------------------------------------------------ 导出
out = os.path.join(tempfile.mkdtemp(), "课件.pdf")
info = app.export_info(LID)
r = app.export_lesson_pdf(LID, out)
assert r["ok"] and r["pages"] == 5 and open(out, "rb").read(5) == b"%PDF-"
assert info["name"].endswith(".pdf") and info["pages"] == 5
print("✓ 导出课件 PDF（%d 页）" % r["pages"])

# ------------------------------------------------ 设置
ref = app.config
r = app.save_settings({"sessionid": "HACK", "auto_monitor": True, "evil": 1,
                       "answer_config": {"mode": "ai_confirm"},
                       "ai_config": {"provider": "codex", "thinking_effort": "xhigh",
                                     "api_key": " k2 ", "base_url": "http://y", "model": "m2",
                                     "concurrency": "99"}})
assert app.config is ref, "save_settings 换掉了 config 对象，正在上的课会读不到新设置"
assert app.config.get("sessionid") != "HACK" and "evil" not in app.config
ai = app.config["ai_config"]
assert ai["provider"] == "openai_responses" and ai["thinking_effort"] == "xhigh"
assert ai["api_key"] == "k2" and ai["concurrency"] == 8
assert app.state()["mode"]["key"] == "ai_confirm" and app.config["auto_monitor"] is True
assert "sessionid" not in app.get_settings()
print("✓ 设置：只接受允许的键、不能改 sessionid、别名归一、数值收敛、config 对象不变")

# ------------------------------------------------ 历史存档（用真实 Lesson）
app.exit_test_mode()
C.get_user_info = lambda s: (0, {"id": 1, "name": "唐琦"})
live = C.Lesson("L900", "组合数学", "R1", app)
live.problems_ls = [{"problemId": 11, "problemType": 1, "page": 3, "body": "Q",
                     "options": [{"key": "A", "value": "a"}], "answers": ["A"],
                     "result": ["A"], "image": ""}]
app.live["L900"] = live
app.history.flush(live)
hist = app.list_history()
assert hist[0]["lessonName"] == "组合数学" and hist[0]["answered"] == 1
H = "h:" + hist[0]["id"]
hd = app.lesson_detail(H)
assert hd["readonly"] and hd["problems"][0]["id"] == "11"
r = app.submit_answer(H, "11", ["A"])
assert r["ok"] is False
r = app.ai_explain(H, "11")
assert r["ok"]
assert app.history.load(hist[0]["id"])["problems"][0]["explanation"] == "考点是……"
print("✓ 历史：真实课程存档、列表统计、只读不可提交、回看时的讲解写回存档")

app.delete_history(hist[0]["id"])
assert app.list_history() == []
print("✓ 删除历史记录")

# ------------------------------------------------ 退出
t = time.time()
app.shutdown()
assert time.time() - t < 3
print("✓ shutdown 迅速返回")
print("\n控制器全部通过")
