# -*- coding: utf-8 -*-
"""课程监听：websocket 收题、签到、自动答题与弹幕。"""
import json
import os
import threading
import time
import traceback

import websocket

from Scripts.AI import call_ai
from Scripts.Utils import (API_BASE, auth_headers, calculate_waittime, dict_result,
                           get_output_dir, get_user_info, http_get, http_post)

WSS_URL = "wss://pro.yuketang.cn/wsapp/"

# 题型常量
TYPE_SINGLE = 1
TYPE_MULTI = 2
TYPE_MULTI_ALT = 3
TYPE_VOTE = 4
TYPE_SUBJECTIVE = 5

TYPE_NAMES = {
    TYPE_SINGLE: "单选题",
    TYPE_MULTI: "多选题",
    TYPE_MULTI_ALT: "多选题",
    TYPE_VOTE: "投票题",
    TYPE_SUBJECTIVE: "主观题",
}


def problem_type_name(problem):
    """题目类型的中文名。"""
    # 带 blanks 的题一律是填空题，problemType 在这种题上并不可靠
    if problem.get("blanks"):
        return "填空题"
    if problem.get("problemType") == TYPE_SUBJECTIVE:
        return "主观题"
    if problem.get("options"):
        return TYPE_NAMES.get(problem.get("problemType"), "选择题")
    return TYPE_NAMES.get(problem.get("problemType"), "题目")


def is_choice(problem):
    return bool(problem.get("options")) and not problem.get("blanks")


def is_multi_choice(problem):
    return is_choice(problem) and problem.get("problemType") in (TYPE_MULTI, TYPE_MULTI_ALT)


def format_answer(problem):
    """把答案渲染成一行可读文本，供列表展示。"""
    answers = problem.get("answers") or []
    if isinstance(answers, dict):
        answers = [answers.get("content", "")]
    if not answers:
        return ""
    text = "、".join(str(a) for a in answers if str(a).strip())
    return text[:60] + "…" if len(text) > 60 else text


class Lesson:
    def __init__(self, lessonid, lessonname, classroomid, main_ui):
        self.classroomid = classroomid
        self.lessonid = lessonid
        self.lessonname = lessonname
        self.sessionid = main_ui.config["sessionid"]
        self.headers = auth_headers(self.sessionid)
        self.receive_danmu = {}
        self.sent_danmu_dict = {}
        self.danmu_dict = {}
        self.problems_ls = []
        self.unlocked_problem = []
        self.classmates_ls = []
        self.finished = False
        self.stopped = False
        self.wsapp = None
        self.add_message = main_ui.add_message
        self.config = main_ui.config
        self.main_ui = main_ui
        # problems_ls 会被 websocket 线程和 UI 线程同时访问
        self._lock = threading.RLock()
        code, rtn = get_user_info(self.sessionid)
        self.user_uid = rtn["id"]
        self.user_uname = rtn["name"]

    # ------------------------------------------------------------ 题目状态

    @property
    def answered_count(self):
        with self._lock:
            return sum(1 for p in self.problems_ls if p.get("result") is not None)

    @property
    def problem_count(self):
        with self._lock:
            return len(self.problems_ls)

    def snapshot_problems(self):
        """返回题目列表的浅拷贝，UI 遍历时不怕被后台线程改动。"""
        with self._lock:
            return list(self.problems_ls)

    def find_problem(self, problemid):
        with self._lock:
            for problem in self.problems_ls:
                if problem.get("problemId") == problemid:
                    return problem
        return None

    def _merge_problems(self, problems):
        """按 problemId 去重后并入题目列表，返回新增数量。"""
        added = 0
        with self._lock:
            known = {p.get("problemId") for p in self.problems_ls}
            for problem in problems:
                pid = problem.get("problemId")
                if pid in known:
                    continue
                problem.setdefault("answers", [])
                self.problems_ls.append(problem)
                known.add(pid)
                added += 1
        if added:
            self.notify_update()
        return added

    def notify_update(self):
        """通知 UI 刷新本课程相关的界面。"""
        notify = getattr(self.main_ui, "on_lesson_updated", None)
        if notify:
            try:
                notify(self)
            except Exception:
                pass

    # ------------------------------------------------------------ PPT / 题目

    def _get_ppt(self, presentationid):
        """获取课程各页 ppt。"""
        url = "%s/api/v3/lesson/presentation/fetch?presentation_id=%s" % (API_BASE, presentationid)
        r = http_get(url, headers=self.headers)
        try:
            return dict_result(r.text)["data"]
        except Exception:
            # 签到获得的 Bearer token 只有约 30 秒有效期，过期后重新签到再试一次
            self.checkin_class()
            r = http_get(url, headers=self.headers)
            return dict_result(r.text)["data"]

    def get_problems(self, presentationid):
        """获取课程 ppt 中的题目，同时把每页截图落到本地。"""
        data = self._get_ppt(presentationid)
        return_problem = []
        folder = os.path.join(get_output_dir(), str(presentationid))
        os.makedirs(folder, exist_ok=True)
        downloaded = 0
        for idx, slide in enumerate(data.get("slides", [])):
            image_path = os.path.join(folder, "%s.jpg" % idx)
            if slide.get("cover") and not os.path.exists(image_path):
                try:
                    r = http_get(slide["cover"], headers=self.headers, timeout=30)
                    if r.status_code == 200:
                        with open(image_path, "wb") as f:
                            f.write(r.content)
                        downloaded += 1
                    else:
                        self.add_message("第%s页截图下载失败（HTTP %s）" % (idx, r.status_code), 4)
                except Exception as exc:
                    self.add_message("第%s页截图下载失败：%s" % (idx, exc), 4)

            if "problem" in slide:
                problem = slide["problem"]
                problem["image"] = image_path
                problem["page"] = idx
                problem.setdefault("answers", [])
                return_problem.append(problem)
        if downloaded:
            self.add_message("%s 已下载 %s 张课件截图" % (self.lessonname, downloaded), 0)
        return return_problem

    def _load_presentation(self, presentationid):
        """拉取一个课件里的题目并并入列表，异常只记录不抛出。"""
        if not presentationid:
            return
        try:
            self._merge_problems(self.get_problems(presentationid))
        except Exception as exc:
            self.add_message("%s 加载课件 %s 失败：%s" % (self.lessonname, presentationid, exc), 4)

    # ------------------------------------------------------------ 答题

    def answer_questions(self, problemid, problemtype, answer, limit):
        """提交答案到雨课堂。"""
        if not answer:
            if limit in (-1, 0):
                meg = "%s 的问题没有找到答案，该题不限时，请尽快前往雨课堂回答" % self.lessonname
            else:
                meg = "%s 的问题没有找到答案，请在 %s 秒内前往雨课堂回答" % (self.lessonname, limit)
            self.add_message(meg, 4)
            return False

        delay_config = self.config.get("answer_config", {}).get("answer_delay", {})
        wait_time = calculate_waittime(limit, delay_config.get("type", 1),
                                       delay_config.get("custom", {}).get("time", 0))
        if wait_time:
            self.add_message("%s 检测到问题，将在 %s 秒后自动回答，答案为 %s"
                             % (self.lessonname, wait_time, answer), 0)
            # 分段睡眠，停止监听时能及时退出
            for _ in range(wait_time):
                if self.stopped:
                    return False
                time.sleep(1)
        else:
            self.add_message("%s 检测到问题，将立即自动回答，答案为 %s"
                             % (self.lessonname, answer), 0)

        data = {"problemId": problemid, "problemType": problemtype,
                "dt": int(time.time()), "result": answer}
        try:
            r = http_post(API_BASE + "/api/v3/lesson/problem/answer",
                          headers=self.headers, data=json.dumps(data))
            return_dict = dict_result(r.text)
        except Exception as exc:
            self.add_message("%s 自动回答失败：%s" % (self.lessonname, exc), 4)
            return False

        if return_dict.get("code") == 0:
            self.add_message("%s 自动回答成功" % self.lessonname, 0)
            problem = self.find_problem(problemid)
            if problem is not None:
                # 标记为已提交，界面上会锁住该题
                problem["result"] = answer
                self.notify_update()
            return True

        self.add_message("%s 自动回答失败，原因：%s"
                         % (self.lessonname, str(return_dict.get("msg", "")).replace("_", " ")), 4)
        return False

    def handle_pushed_problem(self, problemid, limit):
        """处理一道课上推送的题目：已答过则跳过；开启自动答题则作答，否则仅提示。"""
        if problemid is None:
            return
        problem = self.find_problem(problemid)
        if problem is None:
            if limit in (-1, 0):
                meg = "%s 的问题没有找到答案，该题不限时，请尽快前往雨课堂回答" % self.lessonname
            else:
                meg = "%s 的问题没有找到答案，请在 %s 秒内前往雨课堂回答" % (self.lessonname, limit)
            self.add_message(meg, 0)
            return

        if problem.get("result") is not None:
            return          # 已作答过，忽略

        if self.config.get("auto_answer"):
            self.start_answer(problemid, limit)
        else:
            if limit in (-1, 0):
                meg = "%s 推送了新题目（第%s页），该题不限时" % (self.lessonname, problem.get("page", "?"))
            else:
                meg = "%s 推送了新题目（第%s页），剩余 %s 秒" % (self.lessonname, problem.get("page", "?"), limit)
            self.add_message(meg, 7)

    def start_answer(self, problemid, limit):
        """在后台线程里完成「（可选）AI 解答 → 等待 → 提交」的流程。"""
        problem = self.find_problem(problemid)
        if problem is None or problem.get("result") is not None:
            if problem is None:
                self.add_message("%s 的问题没有找到答案，请前往雨课堂回答" % self.lessonname, 0)
            return
        threading.Thread(target=self._answer_worker, args=(problem, limit), daemon=True).start()

    def _answer_worker(self, problem, limit):
        answers = problem.get("answers") or []
        auto_ai = self.config.get("answer_config", {}).get("auto_ai", False)

        if not answers and auto_ai:
            started = time.time()
            self.add_message("%s 第%s页题目尚无答案，正在调用 AI 解答……"
                             % (self.lessonname, problem.get("page", "?")), 0)
            try:
                answers = call_ai(self.config, problem.get("image"))
                problem["answers"] = answers
                self.notify_update()
                self.add_message("%s 第%s页 AI 给出答案：%s"
                                 % (self.lessonname, problem.get("page", "?"), answers), 0)
            except Exception as exc:
                self.add_message("%s 第%s页 AI 解答失败：%s"
                                 % (self.lessonname, problem.get("page", "?"), exc), 4)
            # AI 花掉的时间要从剩余答题时间里扣除
            if limit not in (-1, 0):
                limit = max(0, int(limit - (time.time() - started)))

        payload = answers
        if problem.get("problemType") == TYPE_SUBJECTIVE and answers:
            payload = {"content": answers[0], "pics": []}
        self.answer_questions(problem.get("problemId"), problem.get("problemType"), payload, limit)

    def solve_with_ai(self, problem):
        """给单道题调用 AI，写回 answers 并返回结果（供 UI 调用）。"""
        answers = call_ai(self.config, problem.get("image"))
        problem["answers"] = answers
        self.notify_update()
        return answers

    def submit_problem(self, problem):
        """把界面上已经填好的答案提交到雨课堂。"""
        answers = problem.get("answers") or []
        payload = answers
        if problem.get("problemType") == TYPE_SUBJECTIVE and answers:
            payload = {"content": answers[0], "pics": []}
        data = {"problemId": problem.get("problemId"), "problemType": problem.get("problemType"),
                "dt": int(time.time()), "result": payload}
        r = http_post(API_BASE + "/api/v3/lesson/problem/answer",
                      headers=self.headers, data=json.dumps(data))
        result = dict_result(r.text)
        if result.get("code") == 0:
            problem["result"] = payload
            self.notify_update()
            self.add_message("%s 第%s页已手动提交" % (self.lessonname, problem.get("page", "?")), 0)
            return True
        raise Exception(str(result.get("msg", result.get("code"))).replace("_", " "))

    # ------------------------------------------------------------ websocket

    def on_open(self, wsapp):
        self.handshake = {"op": "hello", "userid": self.user_uid, "role": "student",
                          "auth": self.auth, "lessonid": self.lessonid}
        wsapp.send(json.dumps(self.handshake))

    def checkin_class(self):
        """签到并取回 lessonToken / Authorization。"""
        set_auth = None
        r = None
        for _ in range(3):
            # 签到使用不带 Authorization 的原始请求头，避免旧 token 干扰
            r = http_post(API_BASE + "/api/v3/lesson/checkin",
                          headers=auth_headers(self.sessionid),
                          data=json.dumps({"source": 5, "lessonId": self.lessonid}))
            set_auth = r.headers.get("Set-Auth")
            if set_auth:
                break
            time.sleep(1)
        if not set_auth:
            meg = "%s 签到失败，无法获取 Authorization（可能登录已过期，请重新登录）" % self.lessonname
            self.add_message(meg, 4)
            raise Exception(meg)
        self.headers["Authorization"] = "Bearer %s" % set_auth
        return dict_result(r.text)["data"]["lessonToken"]

    def on_message(self, wsapp, message):
        data = dict_result(message)
        op = data.get("op")
        try:
            if op == "hello":
                timeline = data.get("timeline", [])
                presentations = list({slide["pres"] for slide in timeline
                                      if slide.get("type") == "slide" and slide.get("pres")})
                # 新版协议 hello 中已不再返回 presentation 字段，做兼容处理
                current = data.get("presentation")
                if current and current not in presentations:
                    presentations.append(current)
                for presentationid in presentations:
                    self._load_presentation(presentationid)
                self.add_message("%s 已加载 %s 道题目" % (self.lessonname, self.problem_count), 0)
                # 新版协议 hello 中已不再返回 unlockedproblem 字段，
                # 已推送的题目改为从 timeline 的 problem 条目中获取
                for item in timeline:
                    if item.get("type") == "problem":
                        self.handle_pushed_problem(item.get("prob"), item.get("limit", -1))

            elif op == "unlockproblem":
                problem = data.get("problem", {})
                self.handle_pushed_problem(problem.get("sid"), problem.get("limit", -1))

            elif op == "lessonfinished":
                self.add_message("%s 下课了" % self.lessonname, 0)
                self.finished = True
                wsapp.close()

            elif op in ("presentationupdated", "presentationcreated"):
                self._load_presentation(data.get("presentation"))

            elif op == "newdanmu" and self.config.get("auto_danmu"):
                self._handle_danmu(data)

            elif op == "callpaused":
                name = data.get("name")
                meg = "%s 点名了，点到了：%s" % (self.lessonname, name)
                self.add_message(meg, 5 if self.user_uname == name else 6)

            # 程序在上课中途运行，查询已解锁题目数据得到的返回值，
            # 此处需要筛选未到期的题目进行回答。
            elif op == "probleminfo":
                # 新版协议中已收题的 limit 为 0，与不限时(-1)一样视为不限时处理
                if data.get("limit") not in (-1, 0, None):
                    time_left = int(data["limit"] - (int(data["now"]) - int(data["dt"])) / 1000)
                else:
                    time_left = -1
                if time_left > 0 or time_left == -1:
                    self.handle_pushed_problem(data.get("problemid"), time_left)

        except Exception as exc:
            # 任何消息处理异常都反馈到消息区，避免被 websocket 库静默吞掉
            self.add_message("%s 处理消息(%s)出错：%s" % (self.lessonname, op, exc), 4)
            print(traceback.format_exc())

    def _handle_danmu(self, data):
        current_content = data["danmu"].lower()
        uid = data["userid"]
        sent_danmu_user = User(uid)
        if sent_danmu_user in self.classmates_ls:
            for i in self.classmates_ls:
                if i == sent_danmu_user:
                    self.add_message("%s 课程的 %s%s 发送了弹幕：%s"
                                     % (self.lessonname, i.sno, i.name, data["danmu"]), 2)
                    break
        else:
            self.classmates_ls.append(sent_danmu_user)
            try:
                sent_danmu_user.get_userinfo(self.classroomid, self.headers)
            except Exception:
                sent_danmu_user.sno, sent_danmu_user.name = "", str(uid)
            self.add_message("%s 课程的 %s%s 发送了弹幕：%s"
                             % (self.lessonname, sent_danmu_user.sno, sent_danmu_user.name,
                                data["danmu"]), 2)

        now = time.time()
        # 收到一条弹幕，取出其之前的所有记录，取不到则初始化
        same_content_ls = self.danmu_dict.setdefault(current_content, [])
        # 清除超过 60 秒的弹幕记录
        same_content_ls[:] = [t for t in same_content_ls if now - t <= 60]
        # 如果当前的弹幕没被发过，或者已发送时间超过 60 秒
        if current_content not in self.sent_danmu_dict or now - self.sent_danmu_dict[current_content] > 60:
            limit = self.config.get("danmu_config", {}).get("danmu_limit", 5)
            if len(same_content_ls) + 1 >= limit:
                self.send_danmu(current_content)
                same_content_ls.clear()
                self.sent_danmu_dict[current_content] = now
            else:
                same_content_ls.append(now)

    def _current_problem(self, wsapp, problemid):
        """向 wsapp 发送 probleminfo 以获取已解锁问题的详情。"""
        wsapp.send(json.dumps({"op": "probleminfo", "lessonid": self.lessonid,
                               "problemid": problemid, "msgid": 1}))

    def on_error(self, wsapp, error):
        # websocket 回调异常默认会被库静默吞掉，这里显式上报到消息区
        if not self.stopped:
            self.add_message("%s 监听出现错误：%s" % (self.lessonname, error), 4)

    def on_close(self, wsapp, close_status_code, close_msg):
        if not self.stopped and not self.finished:
            self.add_message("%s 连接已关闭（code=%s）" % (self.lessonname, close_status_code), 8)

    def start_lesson(self, callback):
        try:
            self.auth = self.checkin_class()
            self.add_message("%s 签到成功" % self.lessonname, 0)
            self.wsapp = websocket.WebSocketApp(
                url=WSS_URL, header=self.headers,
                on_open=self.on_open, on_message=self.on_message,
                on_error=self.on_error, on_close=self.on_close)
            self.wsapp.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as exc:
            self.add_message("%s 监听启动失败：%s" % (self.lessonname, exc), 4)
        finally:
            if not self.stopped:
                self.add_message("%s 监听结束" % self.lessonname, 0)
            return callback(self)

    def stop(self):
        """主动停止监听。"""
        self.stopped = True
        if self.wsapp:
            try:
                self.wsapp.close()
            except Exception:
                pass

    def send_danmu(self, content):
        data = {
            "extra": "", "fromStart": "50", "lessonId": self.lessonid,
            "message": content, "requiredCensor": False, "showStatus": True,
            "target": "", "userName": "", "wordCloud": True,
        }
        try:
            r = http_post(API_BASE + "/api/v3/lesson/danmu/send",
                          headers=self.headers, data=json.dumps(data))
            ok = dict_result(r.text).get("code") == 0
        except Exception:
            ok = False
        self.add_message("%s 弹幕%s！内容：%s"
                         % (self.lessonname, "发送成功" if ok else "发送失败", content),
                         0 if ok else 4)

    def get_lesson_info(self):
        r = http_get(API_BASE + "/api/v3/lesson/basic-info", headers=self.headers)
        return dict_result(r.text)["data"]

    def __eq__(self, other):
        return isinstance(other, Lesson) and self.lessonid == other.lessonid

    def __hash__(self):
        return hash(self.lessonid)


class User:
    def __init__(self, uid):
        self.uid = uid
        self.sno = ""
        self.name = str(uid)

    def get_userinfo(self, classroomid, headers):
        url = ("%s/v/course_meta/fetch_user_info_new?query_user_id=%s&classroom_id=%s"
               % (API_BASE, self.uid, classroomid))
        data = dict_result(http_get(url, headers=headers).text)["data"]
        self.sno = data["school_number"]
        self.name = data["name"]

    def __eq__(self, other):
        return isinstance(other, User) and self.uid == other.uid

    def __hash__(self):
        return hash(self.uid)
