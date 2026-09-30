# -*- coding: utf-8 -*-
"""主窗口：课程监听总览 + 系统消息。"""
import datetime
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import requests

from Scripts.Classes import Lesson
from Scripts.Utils import get_config_dir, get_on_lesson, load_config, save_config, test_network
from UI import Theme
from UI.ConfirmDialog import ConfirmAnswerDialog
from UI.Config import ConfigDialog
from UI.Login import LoginDialog
from UI.Notify import Notifier
from UI.Onboarding import OnboardingDialog
from UI.ProblemListWindow import ProblemListWindow
from Scripts.TestData import create_test_lesson, get_test_lessons

# 消息等级 -> (前缀, 文本标签)
LEVELS = {
    0: ("信息", "info"),
    2: ("弹幕", "danmu"),
    4: ("错误", "error"),
    5: ("点名", "callme"),
    6: ("点名", "call"),
    7: ("课程", "lesson"),
    8: ("警告", "warn"),
}

POLL_SECONDS = 5


class MainWindow:
    def __init__(self, master):
        self.master = master
        self.config = load_config()

        self.mode = Theme.init(master, self.config.get("ui_theme", "auto"))
        Theme.apply_icon(master)
        master.geometry("980x760")
        master.minsize(820, 620)

        # 对象变量初始化
        self.is_active = False
        self.test_mode = False
        self._closed = False
        self.user_name = ""

        # 课程相关变量
        self.on_lesson_list = []         # 已签到、加入监听的课程对象
        self.lesson_list = []            # 接口返回的原始课程数据
        self.finished_lesson_ids = set()  # 已下课的课程 id，避免反复重连
        self.problem_windows = {}        # lessonid -> ProblemListWindow
        self.login_state = "checking"
        self._last_login_check = 0.0
        self.notifier = Notifier(master, lambda: self.config)

        self.create_ui()
        self.bind_events()

        self.add_message("程序已启动，配置目录：%s" % get_config_dir(), 0)
        self.refresh_account_state()
        # 第一次打开：弹上手清单（跳过或完成后不再自动弹）
        if not self.config.get("onboarded"):
            self.master.after(700, self.show_onboarding)

    # ------------------------------------------------------------ 界面

    def create_ui(self):
        self.create_header()

        body = ttk.Frame(self.master)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(12, 0))

        # 上下可拖动分栏：课程列表 / 系统消息
        self.paned = ttk.PanedWindow(body, orient=tk.VERTICAL)
        self.paned.pack(fill=tk.BOTH, expand=True)
        self.paned.add(self.build_course_panel(self.paned), weight=3)
        self.paned.add(self.build_message_panel(self.paned), weight=2)
        # ttk 的 weight 只影响拉伸，初始分割位置要自己摆
        self.paned.after(60, lambda: self._place_sash(self.paned, 0.55))

        self.create_statusbar()

    def create_header(self):
        c = Theme.C
        header = tk.Frame(self.master, bg=c["header"])
        header.pack(fill=tk.X)

        inner = tk.Frame(header, bg=c["header"])
        inner.pack(fill=tk.X, padx=18, pady=14)

        left = tk.Frame(inner, bg=c["header"])
        left.pack(side=tk.LEFT)
        tk.Label(left, text="清华大学雨课堂助手", font=Theme.font(17, "bold"),
                 fg=c["header_text"], bg=c["header"]).pack(anchor=tk.W)
        status_row = tk.Frame(left, bg=c["header"])
        status_row.pack(anchor=tk.W, pady=(5, 0))
        self.login_dot = tk.Label(status_row, text="●", font=Theme.font(12),
                                  fg=c["header_sub"], bg=c["header"])
        self.login_dot.pack(side=tk.LEFT)
        self.account_label = tk.Label(status_row, text="正在检查登录……", font=Theme.font(11),
                                      fg=c["header_text"], bg=c["header"])
        self.account_label.pack(side=tk.LEFT, padx=(5, 0))

        right = tk.Frame(inner, bg=c["header"])
        right.pack(side=tk.RIGHT)
        self.active_btn = ttk.Button(right, text="▶  启动监听", style="Accent.TButton", width=12)
        self.active_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.login_btn = ttk.Button(right, text="登录", style="HeaderGhost.TButton", width=8)
        self.login_btn.pack(side=tk.LEFT, padx=4)
        self.config_btn = ttk.Button(right, text="设置", style="HeaderGhost.TButton", width=8)
        self.config_btn.pack(side=tk.LEFT, padx=4)
        self.test_mode_btn = ttk.Button(right, text="测试模式", style="HeaderGhost.TButton", width=10)
        self.test_mode_btn.pack(side=tk.LEFT, padx=4)

    def build_course_panel(self, parent):
        c = Theme.C
        panel = ttk.Frame(parent)

        head = ttk.Frame(panel)
        head.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(head, text="课程列表", style="Section.TLabel").pack(side=tk.LEFT)
        self.course_hint = ttk.Label(head, text="双击课程可查看题目并让 AI 作答",
                                     style="Muted.TLabel")
        self.course_hint.pack(side=tk.LEFT, padx=10)
        self.monitor_badge = Theme.Badge(head, "未监听", "muted")
        self.monitor_badge.pack(side=tk.RIGHT)
        ttk.Button(head, text="上手清单", style="Link.TButton",
                   command=self.show_onboarding).pack(side=tk.RIGHT, padx=(0, 10))

        wrap = Theme.card(panel)
        wrap.pack(fill=tk.BOTH, expand=True)

        columns = ("course_name", "status", "problems", "answered")
        self.tree = ttk.Treeview(wrap, columns=columns, show="headings", selectmode="browse")
        for key, text, width, anchor in (
                ("course_name", "课程名称", 360, tk.W),
                ("status", "状态", 120, tk.CENTER),
                ("problems", "题目数", 100, tk.CENTER),
                ("answered", "已作答", 100, tk.CENTER)):
            self.tree.heading(key, text=text, anchor=anchor)
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key == "course_name"))

        scrollbar = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=1, padx=(0, 1))
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.tree.tag_configure("odd", background=c["surface_alt"])
        self.tree.tag_configure("live", foreground=c["success"])
        self.tree.tag_configure("idle", foreground=c["muted"])

        # 空列表时盖一层提示文字
        self.empty_hint = tk.Label(wrap, text="暂无正在上课的课程\n点击右上角「启动监听」开始，或用「测试模式」熟悉操作",
                                   font=Theme.font(11), fg=c["faint"], bg=c["surface"],
                                   justify=tk.CENTER)
        self.update_empty_hint()
        return panel

    def build_message_panel(self, parent):
        c = Theme.C
        panel = ttk.Frame(parent)

        head = ttk.Frame(panel)
        head.pack(fill=tk.X, pady=(10, 8))
        ttk.Label(head, text="系统消息", style="Section.TLabel").pack(side=tk.LEFT)

        self.autoscroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(head, text="自动滚动", variable=self.autoscroll_var).pack(side=tk.RIGHT)
        ttk.Button(head, text="复制", command=self.copy_log, width=6).pack(side=tk.RIGHT, padx=6)
        ttk.Button(head, text="清空", command=self.clear_log, width=6).pack(side=tk.RIGHT)

        wrap = Theme.card(panel)
        wrap.pack(fill=tk.BOTH, expand=True)

        self.message_text = tk.Text(wrap, wrap=tk.WORD, height=9, bd=0,
                                    font=Theme.font(10), bg=c["surface"], fg=c["text"],
                                    padx=12, pady=10, highlightthickness=0,
                                    insertbackground=c["text"], spacing1=1, spacing3=2)
        bar = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=self.message_text.yview)
        self.message_text.configure(yscrollcommand=bar.set)
        bar.pack(side=tk.RIGHT, fill=tk.Y, pady=1, padx=(0, 1))
        self.message_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.message_text.tag_configure("time", foreground=c["faint"])
        self.message_text.tag_configure("info", foreground=c["text"])
        self.message_text.tag_configure("lesson", foreground=c["accent"])
        self.message_text.tag_configure("danmu", foreground=c["muted"])
        self.message_text.tag_configure("warn", foreground=c["warning"])
        self.message_text.tag_configure("error", foreground=c["danger"])
        self.message_text.tag_configure("call", foreground=c["info"])
        self.message_text.tag_configure("callme", foreground=c["danger"],
                                        font=Theme.font(10, "bold"))
        self.message_text.config(state=tk.DISABLED)
        return panel

    @staticmethod
    def _place_sash(paned, fraction, horizontal=False):
        try:
            size = paned.winfo_width() if horizontal else paned.winfo_height()
            if size > 1:
                paned.sashpos(0, int(size * fraction))
        except tk.TclError:
            pass

    def create_statusbar(self):
        c = Theme.C
        bar = tk.Frame(self.master, bg=c["bg"])
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Separator(bar, orient=tk.HORIZONTAL).pack(fill=tk.X)

        inner = tk.Frame(bar, bg=c["bg"])
        inner.pack(fill=tk.X, padx=16, pady=7)
        self.status_label = tk.Label(inner, text="就绪", font=Theme.font(10),
                                     fg=c["muted"], bg=c["bg"], anchor=tk.W)
        self.status_label.pack(side=tk.LEFT)
        self.ai_label = tk.Label(inner, text="", font=Theme.font(10),
                                 fg=c["muted"], bg=c["bg"])
        self.ai_label.pack(side=tk.RIGHT)

    def bind_events(self):
        self.active_btn.config(command=self.toggle_monitor)
        self.test_mode_btn.config(command=self.toggle_test_mode)
        self.login_btn.config(command=self.show_login)
        self.config_btn.config(command=self.show_config)
        self.tree.bind("<Double-Button-1>", self.on_course_open)
        self.tree.bind("<Return>", self.on_course_open)
        self.master.bind("<F5>", lambda _: self.toggle_monitor())
        self.master.protocol("WM_DELETE_WINDOW", self.on_quit)

    # ------------------------------------------------------------ 状态展示

    def _ui(self, func):
        """把回调丢回主线程执行（监听线程会调用它，不能在这里碰 Tcl 接口）。"""
        if self._closed:
            return
        try:
            self.master.after(0, func)
        except (tk.TclError, RuntimeError):
            pass

    def set_status(self, text):
        self._ui(lambda: self.status_label.config(text=text))

    # 标题栏是深色底，状态灯用亮一些的颜色
    LOGIN_STATES = {
        "checking": ("#9AA1AC", "正在检查登录……", "登录"),
        "ok":       ("#4ADE80", "已登录 · %s", "切换账号"),
        "none":     ("#F87171", "未登录 —— 点右边「登录」用微信扫码", "登录"),
        "expired":  ("#FBBF24", "登录已过期 —— 请点「重新登录」扫码", "重新登录"),
        "offline":  ("#FBBF24", "暂时无法确认登录状态（网络异常）", "登录"),
    }

    def set_login_state(self, state, name=""):
        """更新标题栏状态灯与登录按钮文字（必须在主线程调用）。"""
        self.login_state = state
        color, text, button = self.LOGIN_STATES[state]
        self.login_dot.config(fg=color)
        self.account_label.config(text=text % name if "%s" in text else text)
        self.login_btn.config(text=button)

    def refresh_account_state(self):
        """刷新标题栏的登录信息与状态栏的 AI 配置摘要。"""
        from Scripts.AI import PROVIDERS, normalize_provider
        ai = self.config.get("ai_config", {})
        provider = PROVIDERS[normalize_provider(ai.get("provider"))]["label"].split("（")[0]
        if ai.get("api_key"):
            self.ai_label.config(text="AI：%s · %s" % (provider, ai.get("model") or "默认模型"),
                                 fg=Theme.C["muted"])
        else:
            self.ai_label.config(text="AI：未配置 API Key", fg=Theme.C["warning"])

        if not self.config.get("sessionid"):
            self.set_login_state("none")
            return
        self.set_login_state("checking")
        # 登录态是否还有效需要联网确认，放到后台做
        threading.Thread(target=self._probe_account, daemon=True).start()

    def _probe_account(self, notify_on_fail=False, auto_start=True):
        """联网确认 sessionid 是否有效。网络问题与登录失效分开处理。"""
        from Scripts.Utils import get_user_info
        self._last_login_check = time.time()
        try:
            _, data = get_user_info(self.config["sessionid"])
        except requests.exceptions.RequestException:
            self._ui(lambda: self.set_login_state("offline"))
            return False
        except Exception:
            def expired():
                was_ok = self.login_state == "ok"
                self.set_login_state("expired")
                if notify_on_fail or was_ok:
                    self.add_message("登录已过期，请重新扫码登录", 4)
                    self.notify_event("login", "登录已过期",
                                      "雨课堂登录失效了，监听收不到新题，请重新扫码登录",
                                      urgent=True)
            self._ui(expired)
            return False

        self.user_name = data.get("name", "")
        def ok():
            self.set_login_state("ok", self.user_name)
            # 打开即监听：只在确认登录有效之后才自动开始
            if (auto_start and self.config.get("auto_monitor") and not self.is_active
                    and not self.test_mode):
                self.add_message("已开启「打开即监听」，自动开始监听", 0)
                self.toggle_monitor()
        self._ui(ok)
        return True

    def update_empty_hint(self):
        if self.tree.get_children():
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(relx=0.5, rely=0.45, anchor=tk.CENTER)

    # ------------------------------------------------------------ 课程列表

    def notify_event(self, kind, title, message, urgent=False, lesson=None, problem=None):
        """课程线程与各窗口统一从这里发提醒；点提醒浮窗会打开对应课程/题目。"""
        on_click = None
        if lesson is not None:
            on_click = lambda: self.open_lesson(lesson, problem)
        self.notifier.notify(kind, title, message, urgent=urgent, on_click=on_click)

    def open_lesson(self, lesson, problem=None):
        """打开（或聚焦）某门课的题目列表，可选地直接打开其中一道题。"""
        key = str(lesson.lessonid)
        window = self.problem_windows.get(key)
        if window is None or not window.alive():
            window = ProblemListWindow(self.master, lesson, self)
            self.problem_windows[key] = window
        else:
            window.focus()
        if problem is not None:
            window.open_problem(problem)
        return window

    def on_course_open(self, _event=None):
        """打开选中课程的题目列表。"""
        selection = self.tree.selection()
        if not selection:
            return
        lessonid = selection[0]
        lesson = next((l for l in self.on_lesson_list if str(l.lessonid) == lessonid), None)
        if lesson is None:
            messagebox.showinfo("提示", "该课程还未完成签到，请稍候再试")
            return

        self.open_lesson(lesson)

    def confirm_answer(self, lesson, problem, answers, timeout, on_decided):
        """ai_confirm 模式下由课程线程调用：在主线程弹确认框，结果通过回调返回。"""
        self.notify_event("confirm", "AI 答完了，等你确认",
                          "%s 第%s页 答案：%s（%d 秒内不点就不提交）"
                          % (lesson.lessonname, problem.get("page", "?"),
                             "、".join(map(str, answers)), timeout),
                          urgent=True)

        def show():
            try:
                ConfirmAnswerDialog(self.master, lesson, problem, answers, timeout, on_decided)
            except Exception as exc:
                self.add_message("确认框弹出失败，已跳过提交：%s" % exc, 4)
                on_decided(False)

        if self._closed:
            on_decided(False)
            return
        try:
            self.master.after(0, show)
        except (tk.TclError, RuntimeError):
            on_decided(False)

    def on_lesson_updated(self, lesson=None):
        """题目/答案发生变化时由 Lesson 回调，刷新相关界面。"""
        self._ui(lambda: self._refresh_views(lesson))

    def _refresh_views(self, lesson=None):
        self.update_course_table()
        for key, window in list(self.problem_windows.items()):
            if not window.alive():
                self.problem_windows.pop(key, None)
            elif lesson is None or str(lesson.lessonid) == key:
                window.refresh()

    def update_course_table(self):
        """在主线程中重建课程表格。"""
        def update():
            selected = self.tree.selection()
            self.tree.delete(*self.tree.get_children())

            monitored = {str(l.lessonid): l for l in self.on_lesson_list}
            seen = set()
            rows = []
            for lesson in self.lesson_list:
                lessonid = str(lesson.get("lessonId"))
                seen.add(lessonid)
                obj = monitored.get(lessonid)
                rows.append((lessonid, lesson.get("courseName", "未知课程"), obj,
                             lesson.get("status", 1)))
            # 接口里已经消失但仍在监听的课程也要留在列表里
            for lessonid, obj in monitored.items():
                if lessonid not in seen:
                    rows.append((lessonid, obj.lessonname, obj, 1))

            for idx, (lessonid, name, obj, raw_status) in enumerate(rows):
                if obj is not None:
                    status = "监听中" if not obj.finished else "已下课"
                    problems = str(obj.problem_count)
                    answered = "%s / %s" % (obj.answered_count, obj.problem_count)
                    tag = "live" if not obj.finished else "idle"
                else:
                    status = "进行中" if raw_status == 1 else "未开始"
                    problems = answered = "—"
                    tag = "idle"
                tags = [tag] + (["odd"] if idx % 2 else [])
                self.tree.insert("", "end", iid=lessonid, tags=tuple(tags),
                                 values=(name, status, problems, answered))

            for iid in selected:
                if self.tree.exists(iid):
                    self.tree.selection_set(iid)
            self.update_empty_hint()

        self._ui(update)

    # ------------------------------------------------------------ 测试模式

    def toggle_test_mode(self):
        if self.is_active:
            messagebox.showinfo("提示", "请先停止监听再进入测试模式")
            return

        if not self.test_mode:
            try:
                self.load_test_data()
            except Exception as exc:
                messagebox.showerror("测试模式启动失败",
                                     "无法创建测试课程：%s\n\n测试模式需要先登录以获取用户信息。" % exc)
                return
            self.test_mode = True
            self.test_mode_btn.config(text="退出测试")
            self.active_btn.state(["disabled"])
            self.login_btn.state(["disabled"])
            self.monitor_badge.set("测试模式", "warning")
            self.add_message("已进入测试模式，加载了测试课程及示例题目（双击课程试试）", 7)
        else:
            self.test_mode = False
            self.test_mode_btn.config(text="测试模式")
            self.active_btn.state(["!disabled"])
            self.login_btn.state(["!disabled"])
            self.monitor_badge.set("未监听", "muted")
            self.close_problem_windows()
            self.lesson_list = []
            self.on_lesson_list = []
            self.update_course_table()
            self.add_message("已退出测试模式", 0)

    def load_test_data(self):
        self.lesson_list = get_test_lessons()
        self.on_lesson_list = [create_test_lesson(self)]
        self.update_course_table()

    # ------------------------------------------------------------ 监听

    def toggle_monitor(self):
        if self.test_mode:
            return
        if not self.is_active:
            if not self.config.get("sessionid"):
                self.add_message("请先登录", 8)
                messagebox.showwarning("尚未登录", "请先点击「登录」，用微信扫码后再启动监听。")
                return

            self.is_active = True
            self.active_btn.config(text="■  停止监听", style="Danger.TButton")
            self.monitor_badge.set("监听中", "success")
            self.finished_lesson_ids.clear()
            self.monitor_thread = threading.Thread(target=self.monitor, daemon=True)
            self.monitor_thread.start()
            self.add_message("监听已启动，每 %s 秒检查一次正在上课的课程" % POLL_SECONDS, 0)
        else:
            self.stop_monitor()
            self.add_message("监听已停止", 0)

    def stop_monitor(self):
        self.is_active = False
        self.active_btn.config(text="▶  启动监听", style="Accent.TButton")
        self.monitor_badge.set("未监听", "muted")
        self.set_status("就绪")
        for lesson in list(self.on_lesson_list):
            lesson.stop()
        self.close_problem_windows()
        self.on_lesson_list = []
        self.lesson_list = []
        self.update_course_table()

    def close_problem_windows(self):
        for window in list(self.problem_windows.values()):
            window.close()
        self.problem_windows.clear()

    def monitor(self):
        """后台监听线程：轮询在上的课程并为新课程建立 websocket。"""
        def del_onclass(lesson_obj):
            if lesson_obj in self.on_lesson_list:
                self.on_lesson_list.remove(lesson_obj)
            if getattr(lesson_obj, "finished", False):
                # 课程已下课，记录 id 避免被反复重新加入监听
                self.finished_lesson_ids.add(lesson_obj.lessonid)
            self.update_course_table()

        network_status = True
        sessionid = self.config["sessionid"]

        while self.is_active:
            try:
                self.lesson_list = get_on_lesson(sessionid)
                self.set_status("最近检查：%s · 在上课程 %d 门"
                                % (datetime.datetime.now().strftime("%H:%M:%S"),
                                   len(self.lesson_list)))
            except requests.exceptions.ConnectionError:
                self.add_message("网络异常，监听中断", 8)
                self.set_status("网络异常，等待恢复……")
                network_status = False
            except Exception as exc:
                self.add_message("获取课程列表异常：%s" % exc, 8)
                # 非网络错误多半是登录失效；限流到一分钟查一次
                if time.time() - self._last_login_check > 60:
                    self._probe_account(notify_on_fail=True, auto_start=False)

            # 网络异常处理
            while self.is_active and not network_status:
                if test_network():
                    try:
                        self.lesson_list = get_on_lesson(sessionid)
                    except Exception as exc:
                        self.add_message("恢复网络后获取课程列表异常：%s" % exc, 8)
                    else:
                        network_status = True
                        self.add_message("网络已恢复，监听继续", 8)
                        break
                if not self._interruptible_sleep(5):
                    break
            if not self.is_active:
                break

            self.update_course_table()

            # 检查新课程（可能同时有多门课在上，全部加入）
            for lesson in self.lesson_list:
                lessonid = lesson.get("lessonId")
                if any(obj.lessonid == lessonid for obj in self.on_lesson_list):
                    continue
                if lesson.get("status", 1) != 1 or lessonid in self.finished_lesson_ids:
                    continue
                try:
                    lesson_obj = Lesson(lessonid, lesson.get("courseName", "未知课程"),
                                        lesson.get("classroomId"), self)
                except Exception as exc:
                    self.add_message("课程 %s 初始化失败：%s" % (lesson.get("courseName"), exc), 4)
                    self.finished_lesson_ids.add(lessonid)
                    continue
                self.on_lesson_list.append(lesson_obj)
                threading.Thread(target=lesson_obj.start_lesson, args=(del_onclass,),
                                 daemon=True).start()
                self.add_message("检测到课程 %s 正在上课，已加入监听列表" % lesson_obj.lessonname, 7)
                self.notify_event("lesson", "上课了：%s" % lesson_obj.lessonname,
                                  "已自动签到，开始监听推题", lesson=lesson_obj)
                self.update_course_table()

            if not self._interruptible_sleep(POLL_SECONDS):
                break

    def _interruptible_sleep(self, seconds):
        """可被停止监听打断的睡眠，返回 False 表示应当退出循环。"""
        for _ in range(int(seconds * 4)):
            if not self.is_active:
                return False
            time.sleep(0.25)
        return self.is_active

    # ------------------------------------------------------------ 对话框

    def reload_config(self):
        """原地更新配置。Lesson 持有的是同一个 dict 的引用，
        如果这里换成新对象，正在上的课就再也读不到之后的设置改动了。"""
        fresh = load_config()
        self.config.clear()
        self.config.update(fresh)

    def show_login(self):
        dialog = LoginDialog(self.master, self)
        self.master.wait_window(dialog.top)
        self.reload_config()
        self.refresh_account_state()
        if dialog.login_success:
            self.add_message("登录成功", 0)

    def show_onboarding(self):
        existing = getattr(self, "_onboarding", None)
        try:
            if existing and existing.top.winfo_exists():
                existing.top.lift()
                return
        except tk.TclError:
            pass
        self._onboarding = OnboardingDialog(self)

    def show_config(self, tab=None):
        dialog = ConfigDialog(self.master, self, tab=tab)
        self.master.wait_window(dialog.top)
        self.reload_config()
        self.refresh_account_state()
        if dialog.saved and dialog.theme_changed:
            messagebox.showinfo("提示", "外观设置将在下次启动程序后生效")

    # ------------------------------------------------------------ 消息区

    def add_message(self, message, type=0):
        """把一条消息追加到消息区（可从任意线程调用）。"""
        prefix, tag = LEVELS.get(type, ("其他", "info"))
        stamp = datetime.datetime.now().strftime("%H:%M:%S")

        def add():
            if not self.message_text.winfo_exists():
                return
            self.message_text.config(state=tk.NORMAL)
            self.message_text.insert(tk.END, "%s  " % stamp, "time")
            self.message_text.insert(tk.END, "[%s] " % prefix, tag)
            self.message_text.insert(tk.END, "%s\n" % message, tag)
            # 控制日志长度，避免长时间运行占用内存
            if int(self.message_text.index("end-1c").split(".")[0]) > 2000:
                self.message_text.delete("1.0", "500.0")
            if self.autoscroll_var.get():
                self.message_text.see(tk.END)
            self.message_text.config(state=tk.DISABLED)

        self._ui(add)

    def clear_log(self):
        self.message_text.config(state=tk.NORMAL)
        self.message_text.delete("1.0", tk.END)
        self.message_text.config(state=tk.DISABLED)

    def copy_log(self):
        text = self.message_text.get("1.0", tk.END).strip()
        if not text:
            return
        self.master.clipboard_clear()
        self.master.clipboard_append(text)
        self.set_status("消息已复制到剪贴板")

    # ------------------------------------------------------------ 退出

    def on_quit(self):
        if self.is_active and not messagebox.askokcancel("确认退出", "监听正在运行，确定要退出吗？"):
            return
        self._closed = True
        self.notifier.close()
        self.is_active = False
        for lesson in list(self.on_lesson_list):
            lesson.stop()
        try:
            save_config(self.config)
        except Exception:
            pass
        self.master.destroy()
