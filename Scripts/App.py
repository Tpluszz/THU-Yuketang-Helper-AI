# -*- coding: utf-8 -*-
"""应用控制器：所有业务状态与流程都在这里，界面只负责展示。

界面通过两条通道和它交互：
- 调用方法（查询状态、发起操作）
- 订阅 emit(event, data) 推送的事件（日志、课程变化、提醒、确认请求……）

Lesson 把它当作 main_ui：它实现了 config / add_message / on_lesson_updated /
notify_event / confirm_answer 这几个约定的接口。
"""
import base64
import collections
import datetime
import io
import itertools
import os
import threading
import time

import requests

from Scripts import AI
from Scripts.Classes import (TYPE_SUBJECTIVE, Lesson, format_answer, is_choice,
                             is_multi_choice, problem_type_name)
from Scripts.Export import default_pdf_name, export_pdf, slide_images
from Scripts.History import HistoryLesson, HistoryStore
from Scripts.LoginFlow import LoginFlow
from Scripts.Notify import KINDS as NOTIFY_KINDS
from Scripts.Notify import Notifier
from Scripts.TestData import create_test_lesson, get_test_lessons
from Scripts.Utils import (ANSWER_MODES, get_config_dir, get_on_lesson, get_user_info,
                           load_config, merge_defaults, migrate_answer_mode, save_config,
                           test_network)

VERSION = "2.0.0"
POLL_SECONDS = 5
LOGIN_RECHECK_SECONDS = 60
MAX_LOGS = 600

LEVEL_TAGS = {0: "info", 2: "danmu", 4: "error", 5: "callme", 6: "call", 7: "lesson", 8: "warn"}

MODE_LABELS = {
    "notify":     ("只提示我", "推题时提醒你，全部自己作答"),
    "saved":      ("只交已保存的答案", "提前填好的答案会自动提交；没答案的题只提醒"),
    "ai_confirm": ("AI 解答，问过我再交", "AI 答完弹窗给你过目，同意才提交"),
    "ai_auto":    ("AI 解答并直接交", "全自动，来不及人工核对"),
}

# 设置页允许修改的顶层键（sessionid 等由程序自己管理，不接受界面覆盖）
EDITABLE_KEYS = ("ui_theme", "auto_danmu", "danmu_config", "answer_config",
                 "ai_config", "notify_config", "auto_monitor", "onboarded")


def answer_widget(problem):
    """这道题该用什么控件作答。"""
    if is_multi_choice(problem):
        return "multi"
    if is_choice(problem):
        return "single"
    if problem.get("problemType") == TYPE_SUBJECTIVE and not problem.get("blanks"):
        return "text"
    return "blanks"


def ai_ready(config):
    ai = (config or {}).get("ai_config", {})
    provider = AI.normalize_provider(ai.get("provider"))
    if not (ai.get("api_key") or "").strip():
        return False
    if AI.PROVIDERS[provider]["needs_url"] and not (ai.get("base_url") or "").strip():
        return False
    return bool((ai.get("model") or "").strip()) or provider == "qwen"


class App:
    def __init__(self, emit=None, raise_window=None):
        self._emit = emit or (lambda event, data: None)
        self.raise_window = raise_window
        self.config = load_config()

        self.is_active = False
        self.test_mode = False
        self.closed = False
        self.user_name = ""
        self.login_state = "checking"
        self.status_text = "就绪"
        self.last_check = None
        self._last_login_check = 0.0

        self.live = collections.OrderedDict()     # lessonid -> Lesson
        self.raw_lessons = []                     # 接口返回的在上课程
        self.finished_ids = set()
        self.logs = collections.deque(maxlen=MAX_LOGS)
        self.history = HistoryStore()
        self._history_cache = {}

        self.confirms = {}                        # token -> 待确认
        self._tokens = itertools.count(1)
        self.batches = {}                         # lessonid -> 取消信号
        self.login_flow = None
        self._images = collections.OrderedDict()  # 缩略图缓存
        self._lock = threading.RLock()

        self.notifier = Notifier(lambda: self.config, show_toast=self._toast,
                                 raise_window=self._raise)

    # ================================================================ 事件

    def emit(self, event, data=None):
        if self.closed:
            return
        try:
            self._emit(event, data)
        except Exception:
            pass

    def _toast(self, payload):
        self.emit("toast", payload)

    def _raise(self):
        if self.raise_window:
            try:
                self.raise_window()
            except Exception:
                pass

    # ================================================================ Lesson 约定的接口

    def add_message(self, message, type=0):
        entry = {"t": datetime.datetime.now().strftime("%H:%M:%S"),
                 "level": LEVEL_TAGS.get(type, "info"), "text": str(message)}
        self.logs.append(entry)
        self.emit("log", entry)

    def on_lesson_updated(self, lesson=None):
        if lesson is not None:
            if not getattr(lesson, "readonly", False):
                self.history.schedule_save(lesson)
            self.emit("lesson_updated", {"id": str(lesson.lessonid)})
        self.emit("lessons", self.lessons_payload())

    def notify_event(self, kind, title, message, urgent=False, lesson=None, problem=None):
        target = None
        if lesson is not None:
            target = {"lessonId": str(lesson.lessonid),
                      "problemId": str(problem.get("problemId")) if problem else None}
        self.notifier.notify(kind, title, message, urgent=urgent, target=target)

    def confirm_answer(self, lesson, problem, answers, timeout, on_decided):
        """ai_confirm 模式：把确认请求推给界面，用户的决定通过 confirm_decide 回来。"""
        if self.closed:
            on_decided(False)
            return
        token = "c%d" % next(self._tokens)
        with self._lock:
            self.confirms[token] = {"on_decided": on_decided, "lesson": lesson,
                                    "problem": problem, "deadline": time.time() + timeout}
        self.notify_event("confirm", "AI 答完了，等你确认",
                          "%s 第%s页 答案：%s（%d 秒内不点就不提交）"
                          % (lesson.lessonname, problem.get("page", "?"),
                             "、".join(map(str, answers)), timeout),
                          urgent=True, lesson=lesson, problem=problem)
        payload = self.problem_payload(lesson, problem)
        payload["image"] = self.image_for(problem, 1100)
        self.emit("confirm", {"token": token, "lessonId": str(lesson.lessonid),
                              "lessonName": lesson.lessonname, "problem": payload,
                              "answers": list(answers), "timeout": int(timeout)})
        # 超时后界面那边也要关掉，由 Lesson 自己的计时判定结果
        timer = threading.Timer(timeout + 1, self._expire_confirm, args=(token,))
        timer.daemon = True           # 不能拖住程序退出
        timer.start()

    def confirm_decide(self, token, ok, answers=None):
        with self._lock:
            item = self.confirms.pop(token, None)
        if not item:
            return {"ok": False, "error": "这次确认已经超时或处理过了"}
        if ok and answers:
            # 用户在确认框里改了答案：以用户的为准
            item["problem"]["answers"] = [str(a) for a in answers]
        item["on_decided"](bool(ok))
        self.emit("confirm_closed", {"token": token})
        return {"ok": True}

    def _expire_confirm(self, token):
        with self._lock:
            item = self.confirms.pop(token, None)
        if item:
            self.emit("confirm_closed", {"token": token, "expired": True})

    # ================================================================ 状态

    def mode_key(self):
        return migrate_answer_mode(dict(self.config))["answer_config"].get("mode", "saved")

    def state(self):
        ai = self.config.get("ai_config", {})
        provider = AI.normalize_provider(ai.get("provider"))
        mode = self.mode_key()
        return {
            "version": VERSION,
            "login": {"state": self.login_state, "name": self.user_name},
            "monitor": {"active": self.is_active, "text": self.status_text,
                        "lastCheck": self.last_check},
            "testMode": self.test_mode,
            "ai": {"ready": ai_ready(self.config),
                   "provider": AI.PROVIDERS[provider]["label"].split("（")[0],
                   "model": ai.get("model") or "",
                   "effort": AI.resolve_effort(ai)},
            "mode": {"key": mode, "label": MODE_LABELS[mode][0]},
            "onboarded": bool(self.config.get("onboarded")),
            "theme": self.config.get("ui_theme", "auto"),
        }

    def push_state(self):
        self.emit("state", self.state())

    def lessons_payload(self):
        rows = []
        seen = set()
        for lesson in list(self.live.values()):
            problems = lesson.snapshot_problems()
            submitted = sum(1 for p in problems if p.get("result") is not None)
            ready = sum(1 for p in problems if p.get("result") is None and p.get("answers"))
            if getattr(lesson, "archive", True) is False and self.test_mode:
                status, text = "test", "测试课程"
            elif lesson.finished:
                status, text = "finished", "已下课"
            else:
                status, text = "live", "监听中"
            rows.append({"id": str(lesson.lessonid), "name": lesson.lessonname,
                         "status": status, "statusText": text,
                         "problemCount": len(problems), "submitted": submitted,
                         "ready": ready, "empty": len(problems) - submitted - ready,
                         "slides": len(slide_images(getattr(lesson, "presentations", [])))})
            seen.add(str(lesson.lessonid))
        for raw in self.raw_lessons:
            lid = str(raw.get("lessonId"))
            if lid in seen:
                continue
            rows.append({"id": lid, "name": raw.get("courseName", "未知课程"),
                         "status": "pending", "statusText": "正在签到……",
                         "problemCount": 0, "submitted": 0, "ready": 0, "empty": 0,
                         "slides": 0})
        return rows

    def bootstrap(self):
        """界面加载完成后调用一次，拿到所有初始状态。"""
        return {
            "state": self.state(),
            "lessons": self.lessons_payload(),
            "logs": list(self.logs),
            "meta": self.meta(),
        }

    def meta(self):
        return {
            "providers": [{"key": k, "label": v["label"], "path": v["path"],
                           "needsUrl": v["needs_url"], "urlExample": v["url_example"],
                           "modelExample": v["model_example"], "reasoning": v["reasoning"]}
                          for k, v in AI.PROVIDERS.items()],
            "efforts": [{"key": k, "label": v} for k, v in AI.EFFORT_LABELS.items()],
            "modes": [{"key": k, "label": MODE_LABELS[k][0], "desc": MODE_LABELS[k][1]}
                      for k in ANSWER_MODES],
            "notifyKinds": [{"key": k, "label": v[0]} for k, v in NOTIFY_KINDS.items()],
            "configDir": get_config_dir(),
            "version": VERSION,
        }

    # ================================================================ 登录

    def start(self):
        """界面就绪后调用：检查登录，按设置自动开始监听。"""
        self.add_message("程序已启动（v%s）" % VERSION, 0)
        self.refresh_login()

    def refresh_login(self):
        if not self.config.get("sessionid"):
            self.login_state = "none"
            self.push_state()
            return
        self.login_state = "checking"
        self.push_state()
        threading.Thread(target=self.probe_login, daemon=True).start()

    def probe_login(self, notify_on_fail=False, auto_start=True):
        """联网确认 sessionid 是否有效。网络问题与登录失效分开处理。"""
        self._last_login_check = time.time()
        try:
            _, data = get_user_info(self.config["sessionid"])
        except requests.exceptions.RequestException:
            self.login_state = "offline"
            self.push_state()
            return False
        except Exception:
            was_ok = self.login_state == "ok"
            self.login_state = "expired"
            self.push_state()
            if notify_on_fail or was_ok:
                self.add_message("登录已过期，请重新扫码登录", 4)
                self.notify_event("login", "登录已过期",
                                  "雨课堂登录失效了，监听收不到新题，请重新扫码登录", urgent=True)
            return False
        self.user_name = data.get("name", "")
        self.login_state = "ok"
        self.push_state()
        if (auto_start and self.config.get("auto_monitor") and not self.is_active
                and not self.test_mode):
            self.add_message("已开启「打开即监听」，自动开始监听", 0)
            self.start_monitor()
        return True

    def login_start(self):
        self.login_cancel()

        def on_event(event):
            if event.get("type") == "done":
                self.config["sessionid"] = event["sessionid"]
                save_config(self.config)
                self.add_message("扫码登录成功", 0)
                self.login_flow = None
                self.refresh_login()
            self.emit("login", event)

        self.login_flow = LoginFlow(on_event)
        self.login_flow.start()
        return {"ok": True}

    def login_refresh(self):
        if self.login_flow:
            self.login_flow.refresh()
        return {"ok": True}

    def login_cancel(self):
        if self.login_flow:
            self.login_flow.cancel()
            self.login_flow = None
        return {"ok": True}

    def logout(self):
        self.stop_monitor()
        self.config["sessionid"] = ""
        save_config(self.config)
        self.user_name = ""
        self.login_state = "none"
        self.add_message("已退出登录", 0)
        self.push_state()
        return {"ok": True}

    # ================================================================ 监听

    def start_monitor(self):
        if self.test_mode:
            return {"ok": False, "error": "请先退出测试模式"}
        if self.is_active:
            return {"ok": True}
        if not self.config.get("sessionid"):
            return {"ok": False, "error": "还没登录，请先扫码登录"}
        self.is_active = True
        self.finished_ids.clear()
        self.status_text = "正在检查在上的课……"
        self.push_state()
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        self.add_message("监听已启动，每 %s 秒检查一次正在上课的课程" % POLL_SECONDS, 0)
        return {"ok": True}

    def stop_monitor(self):
        was = self.is_active
        self.is_active = False
        for lesson in list(self.live.values()):
            lesson.stop()
            try:
                self.history.flush(lesson)
            except Exception:
                pass
        if not self.test_mode:
            self.live.clear()
        self.raw_lessons = []
        self.status_text = "就绪"
        if was:
            self.add_message("监听已停止", 0)
        self.push_state()
        self.emit("lessons", self.lessons_payload())
        return {"ok": True}

    def _sleep(self, seconds):
        for _ in range(int(seconds * 4)):
            if not self.is_active:
                return False
            time.sleep(0.25)
        return self.is_active

    def _lesson_ended(self, lesson):
        """Lesson.start_lesson 结束时的回调。"""
        try:
            self.history.flush(lesson)
        except Exception:
            pass
        if lesson.finished:
            self.finished_ids.add(lesson.lessonid)
        # 下课的课留在列表里（标为已下课），方便课后接着看题；停止监听时再清掉
        if not lesson.finished and str(lesson.lessonid) in self.live and not lesson.stopped:
            self.live.pop(str(lesson.lessonid), None)
        self.emit("lessons", self.lessons_payload())

    def _monitor_loop(self):
        network_ok = True
        while self.is_active:
            sessionid = self.config.get("sessionid")
            try:
                self.raw_lessons = get_on_lesson(sessionid)
                self.last_check = datetime.datetime.now().strftime("%H:%M:%S")
                self.status_text = "在上课程 %d 门" % len(self.raw_lessons)
            except requests.exceptions.ConnectionError:
                self.add_message("网络异常，监听中断", 8)
                self.status_text = "网络异常，等待恢复……"
                network_ok = False
            except Exception as exc:
                self.add_message("获取课程列表异常：%s" % exc, 8)
                # 非网络错误多半是登录失效；限流到一分钟查一次
                if time.time() - self._last_login_check > LOGIN_RECHECK_SECONDS:
                    self.probe_login(notify_on_fail=True, auto_start=False)
            self.push_state()

            while self.is_active and not network_ok:
                if test_network():
                    try:
                        self.raw_lessons = get_on_lesson(sessionid)
                    except Exception as exc:
                        self.add_message("恢复网络后获取课程列表异常：%s" % exc, 8)
                    else:
                        network_ok = True
                        self.add_message("网络已恢复，监听继续", 8)
                        break
                if not self._sleep(5):
                    break
            if not self.is_active:
                break

            for raw in list(self.raw_lessons):
                lid = raw.get("lessonId")
                if str(lid) in self.live or lid in self.finished_ids:
                    continue
                if raw.get("status", 1) != 1:
                    continue
                try:
                    lesson = Lesson(lid, raw.get("courseName", "未知课程"),
                                    raw.get("classroomId"), self)
                except Exception as exc:
                    self.add_message("课程 %s 初始化失败：%s" % (raw.get("courseName"), exc), 4)
                    self.finished_ids.add(lid)
                    continue
                self.live[str(lid)] = lesson
                threading.Thread(target=lesson.start_lesson, args=(self._lesson_ended,),
                                 daemon=True).start()
                self.add_message("检测到课程 %s 正在上课，已加入监听" % lesson.lessonname, 7)
                self.notify_event("lesson", "上课了：%s" % lesson.lessonname,
                                  "已自动签到，开始监听推题", lesson=lesson)
            self.emit("lessons", self.lessons_payload())

            if not self._sleep(POLL_SECONDS):
                break

    # ================================================================ 测试模式

    def enter_test_mode(self):
        if self.is_active:
            return {"ok": False, "error": "请先停止监听再进入测试模式"}
        lesson = create_test_lesson(self)
        self.test_mode = True
        self.live.clear()
        self.live[str(lesson.lessonid)] = lesson
        self.raw_lessons = get_test_lessons()
        self.add_message("已进入测试模式：加载了示例课程和 5 道示例题，所有操作都不会发到雨课堂", 7)
        self.push_state()
        self.emit("lessons", self.lessons_payload())
        return {"ok": True, "lessonId": str(lesson.lessonid)}

    def exit_test_mode(self):
        self.test_mode = False
        self.live.clear()
        self.raw_lessons = []
        self.add_message("已退出测试模式", 0)
        self.push_state()
        self.emit("lessons", self.lessons_payload())
        return {"ok": True}

    # ================================================================ 课程与题目

    def get_lesson(self, lesson_id):
        lesson_id = str(lesson_id)
        if lesson_id in self.live:
            return self.live[lesson_id]
        if lesson_id.startswith("h:"):
            cached = self._history_cache.get(lesson_id)
            if cached is None:
                record = self.history.load(lesson_id[2:])
                cached = HistoryLesson(record, self.history, self.config)
                self._history_cache[lesson_id] = cached
            return cached
        raise KeyError("找不到这门课（可能已经停止监听）")

    def _problem(self, lesson_id, problem_id):
        lesson = self.get_lesson(lesson_id)
        problem = lesson.find_problem(problem_id)
        if problem is None:
            # 雨课堂的 problemId 可能是数字，界面传回来是字符串
            for p in lesson.snapshot_problems():
                if str(p.get("problemId")) == str(problem_id):
                    problem = p
                    break
        if problem is None:
            raise KeyError("找不到这道题")
        return lesson, problem

    def problem_payload(self, lesson, problem):
        answers = problem.get("answers") or []
        if isinstance(answers, dict):
            answers = [answers.get("content", "")]
        result = problem.get("result")
        return {
            "id": str(problem.get("problemId")),
            "page": problem.get("page"),
            "type": problem_type_name(problem),
            "widget": answer_widget(problem),
            "body": (problem.get("body") or "").strip(),
            "options": [{"key": o.get("key", ""), "value": o.get("value", "")}
                        for o in (problem.get("options") or [])],
            "blanks": len(problem.get("blanks") or []) or 1,
            "answers": [str(a) for a in answers],
            "answerText": format_answer(problem),
            "submitted": result is not None,
            "explanation": problem.get("explanation") or "",
            "review": problem.get("review"),
            "hasImage": bool(problem.get("image") and os.path.exists(problem.get("image"))),
        }

    def lesson_detail(self, lesson_id):
        lesson = self.get_lesson(lesson_id)
        problems = [self.problem_payload(lesson, p) for p in lesson.snapshot_problems()]
        return {
            "id": str(lesson.lessonid),
            "name": lesson.lessonname,
            "readonly": bool(getattr(lesson, "readonly", False)),
            "finished": bool(getattr(lesson, "finished", False)),
            "test": getattr(lesson, "archive", True) is False,
            "slides": len(slide_images(getattr(lesson, "presentations", []))),
            "problems": problems,
            "batch": lesson_id in self.batches,
        }

    def image_for(self, problem, width=480):
        """把题目截图缩放后转成 data URI；按 (路径, 宽度, 修改时间) 缓存。"""
        path = problem.get("image")
        if not path or not os.path.exists(path):
            return None
        key = (path, width, os.path.getmtime(path))
        with self._lock:
            if key in self._images:
                self._images.move_to_end(key)
                return self._images[key]
        from PIL import Image
        try:
            img = Image.open(path)
            img.load()
        except Exception:
            return None
        if img.mode != "RGB":
            img = img.convert("RGB")
        if img.width > width:
            img = img.resize((width, max(1, int(img.height * width / img.width))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=82)
        uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        with self._lock:
            self._images[key] = uri
            while len(self._images) > 240:
                self._images.popitem(last=False)
        return uri

    def problem_image(self, lesson_id, problem_id, width=480):
        _, problem = self._problem(lesson_id, problem_id)
        return self.image_for(problem, int(width))

    # ---------------------------------------------------------------- 作答

    def _changed(self, lesson):
        lesson.notify_update() if getattr(lesson, "readonly", False) else self.on_lesson_updated(lesson)

    def save_answer(self, lesson_id, problem_id, answers):
        lesson, problem = self._problem(lesson_id, problem_id)
        if problem.get("result") is not None:
            return {"ok": False, "error": "这道题已经提交过了，不能再改"}
        problem["answers"] = [str(a) for a in (answers or []) if str(a).strip()]
        self._changed(lesson)
        return {"ok": True, "problem": self.problem_payload(lesson, problem)}

    def submit_answer(self, lesson_id, problem_id, answers):
        lesson, problem = self._problem(lesson_id, problem_id)
        if getattr(lesson, "readonly", False):
            return {"ok": False, "error": "这是历史记录，课已经结束，不能再提交"}
        if problem.get("result") is not None:
            return {"ok": False, "error": "这道题已经提交过了"}
        answers = [str(a) for a in (answers or []) if str(a).strip()]
        if not answers:
            return {"ok": False, "error": "还没有填写答案"}
        problem["answers"] = answers
        try:
            lesson.submit_problem(problem)
        except Exception as exc:
            return {"ok": False, "error": "提交失败：%s" % exc}
        self._changed(lesson)
        return {"ok": True, "problem": self.problem_payload(lesson, problem)}

    def _need_ai(self):
        if not ai_ready(self.config):
            raise AI.AIError("AI 还没配置好：请到「设置 → AI 服务」填好接口地址、模型和 API Key")

    def ai_solve(self, lesson_id, problem_id):
        lesson, problem = self._problem(lesson_id, problem_id)
        try:
            self._need_ai()
            answers = AI.call_ai(self.config, problem.get("image"))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if problem.get("result") is None:
            problem["answers"] = answers
            self._changed(lesson)
        return {"ok": True, "answers": answers, "problem": self.problem_payload(lesson, problem)}

    def ai_explain(self, lesson_id, problem_id):
        lesson, problem = self._problem(lesson_id, problem_id)
        try:
            self._need_ai()
            result = AI.explain_problem(self.config, problem.get("image"))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        problem["explanation"] = result["explanation"]
        # 还没答的题顺手把答案也填上；已有答案的不动，免得覆盖用户的选择
        if problem.get("result") is None and not problem.get("answers") and result["answer"]:
            problem["answers"] = result["answer"]
        self._changed(lesson)
        return {"ok": True, "answer": result["answer"], "explanation": result["explanation"],
                "problem": self.problem_payload(lesson, problem)}

    def ai_review(self, lesson_id, problem_id, answers):
        lesson, problem = self._problem(lesson_id, problem_id)
        try:
            self._need_ai()
            result = AI.review_answer(self.config, problem.get("image"), answers)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        problem["review"] = dict(result, of=[str(a) for a in answers])
        self._changed(lesson)
        return dict(result, ok=True, agreed=result["ok"],
                    problem=self.problem_payload(lesson, problem))

    # ---------------------------------------------------------------- 批量解题

    def solve_all(self, lesson_id):
        lesson = self.get_lesson(lesson_id)
        if lesson_id in self.batches:
            return {"ok": False, "error": "已经在解答了"}
        try:
            self._need_ai()
        except AI.AIError as exc:
            return {"ok": False, "error": str(exc)}
        targets = [p for p in lesson.snapshot_problems()
                   if p.get("result") is None and not p.get("answers")]
        if not targets:
            return {"ok": False, "error": "没有需要解答的题目"}
        cancel = threading.Event()
        self.batches[lesson_id] = cancel
        threading.Thread(target=self._solve_all, args=(lesson_id, lesson, targets, cancel),
                         daemon=True).start()
        return {"ok": True, "total": len(targets)}

    def cancel_solve_all(self, lesson_id):
        cancel = self.batches.get(lesson_id)
        if cancel:
            cancel.set()
        return {"ok": True}

    def _solve_all(self, lesson_id, lesson, targets, cancel):
        total = len(targets)
        stat = {"done": 0, "ok": 0, "fail": 0}
        lock = threading.Lock()
        concurrency = max(1, min(8, int(self.config.get("ai_config", {}).get("concurrency", 3))))
        queue = collections.deque(targets)

        def progress(finished=False):
            self.emit("batch", dict(stat, lessonId=lesson_id, total=total,
                                    finished=finished, cancelled=cancel.is_set()))

        def worker():
            # 用 daemon 线程而不是线程池：关窗口时不能被卡在途的 AI 请求拖住
            while not cancel.is_set() and not self.closed:
                with lock:
                    if not queue:
                        return
                    problem = queue.popleft()
                try:
                    answers = AI.call_ai(self.config, problem.get("image"))
                    if problem.get("result") is None:
                        problem["answers"] = answers
                    with lock:
                        stat["ok"] += 1
                except Exception as exc:
                    with lock:
                        stat["fail"] += 1
                    self.add_message("%s 第%s页 AI 解答失败：%s"
                                     % (lesson.lessonname, problem.get("page", "?"), exc), 4)
                with lock:
                    stat["done"] += 1
                self._changed(lesson)
                progress()

        progress()
        threads = [threading.Thread(target=worker, daemon=True) for _ in range(concurrency)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.batches.pop(lesson_id, None)
        progress(finished=True)
        self.add_message("%s 批量解答结束：成功 %d，失败 %d%s"
                         % (lesson.lessonname, stat["ok"], stat["fail"],
                            "（已手动停止）" if cancel.is_set() else ""), 0)

    # ================================================================ 历史与导出

    def list_history(self):
        return self.history.list()

    def delete_history(self, record_id):
        self.history.delete(record_id)
        self._history_cache.pop("h:" + record_id, None)
        return {"ok": True}

    def export_info(self, lesson_id):
        lesson = self.get_lesson(lesson_id)
        started = None
        if isinstance(lesson, HistoryLesson):
            started = lesson.record.get("startedAt")
        elif getattr(lesson, "started_at", None):
            started = datetime.datetime.fromtimestamp(lesson.started_at).isoformat()
        return {"name": default_pdf_name(lesson.lessonname, started),
                "pages": len(slide_images(getattr(lesson, "presentations", [])))}

    def export_lesson_pdf(self, lesson_id, out_path):
        lesson = self.get_lesson(lesson_id)
        images = slide_images(getattr(lesson, "presentations", []))
        if not images:
            return {"ok": False, "error": "这节课还没有下载到课件截图"}
        try:
            pages = export_pdf(images, out_path)
        except Exception as exc:
            return {"ok": False, "error": "导出失败：%s" % exc}
        self.add_message("已导出课件 PDF（%d 页）：%s" % (pages, out_path), 0)
        return {"ok": True, "path": out_path, "pages": pages}

    # ================================================================ 设置

    def get_settings(self):
        cfg = merge_defaults(self.config)
        migrate_answer_mode(cfg)
        cfg["ai_config"]["thinking_effort"] = AI.resolve_effort(cfg["ai_config"])
        cfg.pop("sessionid", None)
        return cfg

    def save_settings(self, incoming):
        """只接受允许修改的键，并原地更新配置（Lesson 持有同一个 dict 的引用）。"""
        new = dict(self.config)
        for key in EDITABLE_KEYS:
            if key in (incoming or {}):
                new[key] = incoming[key]
        answer = new.setdefault("answer_config", {})
        if answer.get("mode") not in ANSWER_MODES:
            answer["mode"] = "saved"
        migrate_answer_mode(new)
        ai = new.setdefault("ai_config", {})
        ai["provider"] = AI.normalize_provider(ai.get("provider"))
        ai["thinking_effort"] = AI.normalize_effort(ai.get("thinking_effort"))
        ai.pop("enable_thinking", None)
        for k in ("api_key", "base_url", "model"):
            ai[k] = str(ai.get(k) or "").strip()
        try:
            ai["concurrency"] = max(1, min(8, int(ai.get("concurrency", 3))))
        except (TypeError, ValueError):
            ai["concurrency"] = 3
        merged = merge_defaults(new)
        save_config(merged)
        self.config.clear()
        self.config.update(merged)
        self.push_state()
        return {"ok": True, "settings": self.get_settings()}

    def set_onboarded(self, extra=None):
        incoming = dict(extra or {})
        incoming["onboarded"] = True
        if "mode" in incoming:
            answer = dict(self.config.get("answer_config") or {})
            answer["mode"] = incoming.pop("mode")
            incoming["answer_config"] = answer
        return self.save_settings(incoming)

    def test_ai(self, ai_config):
        try:
            return {"ok": True, "message": AI.test_connection(ai_config)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def list_models(self, ai_config):
        try:
            return {"ok": True, "models": AI.list_models(ai_config)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def test_notify(self, notify_config):
        preview = {"notify_config": dict(notify_config or {}, enabled=True, problem=True)}
        Notifier(lambda: preview, show_toast=self._toast).notify(
            "problem", "测试提醒", "上课推题时，你会收到这样的提醒", force=True)
        return {"ok": True}

    # ================================================================ 退出

    def shutdown(self):
        self.is_active = False
        self.login_cancel()
        for cancel in self.batches.values():
            cancel.set()
        for lesson in list(self.live.values()):
            lesson.stop()
            try:
                self.history.flush(lesson)
            except Exception:
                pass
        with self._lock:
            pending = list(self.confirms.values())
            self.confirms.clear()
        for item in pending:
            try:
                item["on_decided"](False)
            except Exception:
                pass
        try:
            save_config(self.config)
        except Exception:
            pass
        self.closed = True
