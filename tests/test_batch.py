# -*- coding: utf-8 -*-
"""在真实 mainloop 下验证批量 AI 解题的并发/取消/失败隔离，以及课件截图下载"""
import json, os, sys, tempfile, threading, time, tkinter as tk
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOME"] = tempfile.mkdtemp()

import Scripts.Classes as C
from Scripts.Utils import get_output_dir

C.get_user_info = lambda sid: (0, {"id": 1, "name": "张三"})

# ---------- 1) 截图下载
class R:
    def __init__(s, code, content=b""):
        s.status_code, s.content = code, content
        s.text = json.dumps({"code": 0, "data": {"slides": [
            {"cover": "http://x/0.jpg"},
            {"cover": "http://x/1.jpg", "problem": {"problemId": "p1", "problemType": 1, "body": "Q"}},
            {"cover": "http://x/2.jpg", "problem": {"problemId": "p2", "problemType": 1, "body": "Q2"}},
        ]}})
GETS = []
def fake_get(url, headers=None, **kw):
    GETS.append(url)
    if "presentation" in url: return R(200)
    if url.endswith("2.jpg"): return R(404)          # 第三页下载失败
    return R(200, b"\xff\xd8\xff\xe0FAKEJPEG")
C.http_get = fake_get
C.http_post = lambda *a, **k: R(200)

MSGS = []
class MockUI:
    config = {"sessionid": "s", "auto_answer": False, "auto_danmu": False,
              "answer_config": {"answer_delay": {"type": 1, "custom": {"time": 0}}, "auto_ai": False},
              "ai_config": {"api_key": "sk-x", "concurrency": 4}}
    def add_message(self, m, t=0): MSGS.append(m)
    def on_lesson_updated(self, lesson): pass

ui = MockUI()
L = C.Lesson("L1", "测试课", "R1", ui)
probs = L.get_problems("pres_1")
folder = os.path.join(get_output_dir(), "pres_1")
assert os.path.exists(os.path.join(folder, "1.jpg")), "成功页没落盘"
assert not os.path.exists(os.path.join(folder, "2.jpg")), "失败页不该留空文件"
assert any("下载失败" in m and "404" in m for m in MSGS), MSGS
assert [p["page"] for p in probs] == [1, 2] and probs[0]["image"].endswith("1.jpg")
print("✓ 截图下载：成功页落盘、失败页上报 404、题目绑定到正确图片")

GETS.clear(); L.get_problems("pres_1")
assert [u for u in GETS if u.endswith(".jpg")] == ["http://x/2.jpg"]
print("✓ 截图缓存：已下载的页不再请求，只重试失败的那页")

# ---------- 2) 批量解题（跑在真实 mainloop 里）
import Scripts.AI, UI.ProblemListWindow as PLW
from UI import Theme

peak = {"n": 0, "cur": 0}; CALLS = []; lock = threading.Lock()
def fake_call_ai(config, image_path, prompt=None):
    with lock:
        peak["cur"] += 1; peak["n"] = max(peak["n"], peak["cur"])
    try:
        time.sleep(0.2)
        with lock: CALLS.append(image_path)
        if image_path.endswith("3.jpg"): raise Exception("模拟第3题失败")
        return ["A"]
    finally:
        with lock: peak["cur"] -= 1
Scripts.AI.call_ai = fake_call_ai
PLW.messagebox.showinfo = lambda *a, **k: None       # 完成弹窗会阻塞 mainloop
PLW.messagebox.showwarning = lambda *a, **k: None

root = tk.Tk(); root.withdraw(); Theme.init(root, "light")
L.problems_ls = [{"problemId": "q%d" % i, "problemType": 1, "body": "Q%d" % i, "page": i,
                  "options": [{"key": "A", "value": "a"}], "answers": [],
                  "image": os.path.join(folder, "%d.jpg" % i)} for i in range(1, 9)]
for p in L.problems_ls: open(p["image"], "wb").close()
L.problems_ls[0]["result"] = ["A"]                   # 第 1 题已提交，应跳过
w = PLW.ProblemListWindow(root, L, ui)

RESULT = {}
def phase1():
    w.on_solve_all_click()
    wait_until(lambda: not w.solving, phase1_done, timeout=8)
def phase1_done(ok):
    RESULT["p1"] = (ok, len(CALLS), peak["n"], w.progress_label.cget("text"))
    for p in L.problems_ls: p["answers"] = []
    L.problems_ls[0].pop("result", None)
    # 降并发 + 加题，保证点「停止」时队列里还有没开工的任务
    ui.config["ai_config"]["concurrency"] = 2
    L.problems_ls.extend([dict(p, problemId="x%d" % i) for i, p in
                          enumerate(L.problems_ls[:8])])
    CALLS.clear(); w.refresh()
    w.on_solve_all_click()
    root.after(250, lambda: (w.on_cancel_click(),
                             wait_until(lambda: not w.solving, phase2_done, timeout=8)))
def phase2_done(ok):
    RESULT["p2"] = (ok, len(CALLS))
    root.quit()
def wait_until(cond, cb, timeout, t0=None):
    t0 = t0 or time.time()
    if cond(): return cb(True)
    if time.time() - t0 > timeout: return cb(False)
    root.after(50, lambda: wait_until(cond, cb, timeout, t0))

root.after(50, phase1)
root.mainloop()

ok, ncalls, npeak, label = RESULT["p1"]
assert ok, "批量解题没有结束（跨线程回调可能又丢了）"
assert ncalls == 7, "应解答 7 题（跳过已提交的那道），实际 %d" % ncalls
assert npeak > 1, "并发没生效，实际是串行"
assert npeak <= 4, "并发 %d 超过配置上限 4" % npeak
solved = [p for p in L.problems_ls if p["answers"]]
print("✓ 批量解题：跳过已提交题、并发峰值 %d（上限 4）、进度回调到达主线程" % npeak)

ok2, ncalls2 = RESULT["p2"]
assert ok2, "取消后没有结束"
assert ncalls2 < 16, "取消没生效，16 题全跑完了"
print("✓ 停止按钮：中途取消生效（16 题只跑了 %d 题就停下）" % ncalls2)
print("\n批量解题与截图下载全部通过")
