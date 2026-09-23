# -*- coding: utf-8 -*-
"""题目详情窗口：左边看截图，右边填答案。"""
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from Scripts.Classes import is_choice, is_multi_choice, problem_type_name
from UI import Theme


class ProblemDetailWindow:
    """问题详情窗口。"""

    def __init__(self, master, problem, lesson=None, parent_window=None):
        self.problem = problem
        self.lesson = lesson
        self.parent_window = parent_window
        self.config = getattr(lesson, "config", None) or {}
        self.locked = problem.get("result") is not None

        self._photo = None
        self._source_image = None
        self._resize_job = None
        self._area = (0, 0)      # 截图可用区域，来自容器的 Configure 事件
        self.answer_var = tk.StringVar()
        self.answer_vars = []
        self.answer_entries = []
        self.mode = "blanks"
        self._closed = False

        self.window = tk.Toplevel(master)
        self.window.title("第 %s 页 · %s" % (problem.get("page", "?"), problem_type_name(problem)))
        self.window.configure(bg=Theme.C["bg"])
        Theme.apply_icon(self.window)
        Theme.center(self.window, 1040, 700)
        self.window.minsize(780, 520)

        self.create_ui()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda _: self.close())
        self.window.bind("<Control-Return>", lambda _: self.on_save_click())
        self.window.after(200, self.render_image)

    # ------------------------------------------------------------ 界面

    def create_ui(self):
        c = Theme.C
        root = ttk.Frame(self.window)
        root.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)

        # --- 顶部信息
        head = ttk.Frame(root)
        head.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(head, text="第 %s 页" % self.problem.get("page", "?"),
                  style="Section.TLabel").pack(side=tk.LEFT)
        Theme.Badge(head, problem_type_name(self.problem), "accent").pack(side=tk.LEFT, padx=8)
        if self.locked:
            Theme.Badge(head, "已提交 · 不可修改", "muted").pack(side=tk.LEFT)

        panes = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True)
        panes.add(self.build_image_pane(panes), weight=3)
        panes.add(self.build_answer_pane(panes), weight=2)
        # 初始把 55% 的宽度留给截图
        panes.after(80, lambda: self._place_sash(panes, 0.55))

        # --- 底部按钮
        footer = ttk.Frame(root)
        footer.pack(fill=tk.X, pady=(12, 0))
        self.status_label = ttk.Label(footer, text="", style="Muted.TLabel")
        self.status_label.pack(side=tk.LEFT)

        ttk.Button(footer, text="关闭", command=self.close, width=8).pack(side=tk.RIGHT)
        self.save_btn = ttk.Button(footer, text="保存答案", command=self.on_save_click, width=10)
        self.save_btn.pack(side=tk.RIGHT, padx=8)
        self.submit_btn = ttk.Button(footer, text="提交到雨课堂", style="Accent.TButton",
                                     command=self.on_submit_click, width=14)
        self.submit_btn.pack(side=tk.RIGHT)

        if self.locked:
            self.save_btn.state(["disabled"])
            self.submit_btn.state(["disabled"])
            self.set_status("该题已提交到雨课堂，答案不可再修改", "muted")
        elif self.lesson is None:
            self.submit_btn.state(["disabled"])

    @staticmethod
    def _place_sash(panes, fraction):
        try:
            width = panes.winfo_width()
            if width > 1:
                panes.sashpos(0, int(width * fraction))
        except tk.TclError:
            pass

    def build_image_pane(self, parent):
        c = Theme.C
        pane = ttk.Frame(parent)
        ttk.Label(pane, text="题目截图", style="Section.TLabel").pack(anchor=tk.W, pady=(0, 6))

        wrap = Theme.card(pane)
        wrap.pack(fill=tk.BOTH, expand=True, padx=(0, 8))
        self.image_container = tk.Label(wrap, bg=c["surface"], fg=c["faint"],
                                        font=Theme.font(11), text="正在加载截图……")
        self.image_container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        wrap.bind("<Configure>", self.on_image_area_resize)
        self.load_image()
        return pane

    def build_answer_pane(self, parent):
        c = Theme.C
        pane = ttk.Frame(parent)

        ttk.Label(pane, text="题干", style="Section.TLabel").pack(anchor=tk.W, pady=(0, 6))
        body_wrap = Theme.card(pane)
        body_wrap.pack(fill=tk.X)
        body = tk.Text(body_wrap, wrap=tk.WORD, height=3, bd=0, highlightthickness=0,
                       font=Theme.font(10), bg=c["surface"], fg=c["text"], padx=10, pady=8)
        body.insert(tk.END, (self.problem.get("body") or "（此题没有文字题干，请看左侧截图）").strip())
        body.config(state=tk.DISABLED)
        body.pack(fill=tk.X, padx=1, pady=1)

        ai_row = ttk.Frame(pane)
        ai_row.pack(fill=tk.X, pady=(12, 6))
        ttk.Label(ai_row, text="您的答案", style="Section.TLabel").pack(side=tk.LEFT)
        self.ai_btn = ttk.Button(ai_row, text="✨  让 AI 作答", command=self.on_ai_answer_click)
        self.ai_btn.pack(side=tk.RIGHT)
        if self.locked:
            self.ai_btn.state(["disabled"])

        answer_wrap = Theme.card(pane)
        answer_wrap.pack(fill=tk.BOTH, expand=True)
        outer, self.answer_frame = Theme.scrollable(answer_wrap)
        outer.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self.build_answer_widgets(self.answer_frame)
        return pane

    def build_answer_widgets(self, parent):
        """按题型渲染答题控件。"""
        options = self.problem.get("options") or []
        answers = self.problem.get("answers") or []
        if isinstance(answers, dict):
            answers = [answers.get("content", "")]
        state = tk.DISABLED if self.locked else tk.NORMAL

        # 记下实际渲染的答题模式，读写答案时按它来，避免和题型判断脱节
        if is_multi_choice(self.problem):
            self.mode = "multi"
        elif is_choice(self.problem):
            self.mode = "single"
        elif self.problem.get("problemType") == 5 and not self.problem.get("blanks"):
            self.mode = "text"
        else:
            self.mode = "blanks"
        self._closed = False

        if self.mode == "multi":
            for option in options:
                key = option.get("key", "")
                var = tk.BooleanVar(value=key in answers)
                self.answer_vars.append((key, var))
                ttk.Checkbutton(parent, text="%s.  %s" % (key, option.get("value", "")),
                                variable=var, state=state).pack(fill=tk.X, padx=12, pady=4)

        elif self.mode == "single":
            self.answer_var.set(answers[0] if answers else "")
            for option in options:
                key = option.get("key", "")
                ttk.Radiobutton(parent, text="%s.  %s" % (key, option.get("value", "")),
                                variable=self.answer_var, value=key,
                                state=state).pack(fill=tk.X, padx=12, pady=4)

        elif self.mode == "text":
            ttk.Label(parent, text="主观题作答：", style="Muted.TLabel").pack(anchor=tk.W, padx=12, pady=(10, 4))
            text = tk.Text(parent, height=8, wrap=tk.WORD, bd=1, relief="solid",
                           font=Theme.font(10), bg=Theme.C["surface"], fg=Theme.C["text"],
                           highlightthickness=0, padx=8, pady=6)
            text.insert(tk.END, answers[0] if answers else "")
            if self.locked:
                text.config(state=tk.DISABLED)
            text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
            self.subjective_text = text

        else:
            blanks = self.problem.get("blanks") or [""]
            for i in range(len(blanks)):
                row = ttk.Frame(parent)
                row.pack(fill=tk.X, padx=12, pady=5)
                ttk.Label(row, text="填空 %d" % (i + 1), width=8).pack(side=tk.LEFT)
                entry = ttk.Entry(row, state=state)
                entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
                if i < len(answers):
                    entry.insert(0, str(answers[i]))
                self.answer_entries.append(entry)

    # ------------------------------------------------------------ 图片

    def load_image(self):
        path = self.problem.get("image", "")
        if not path or not os.path.exists(path):
            self.image_container.config(text="没有找到题目截图", image="")
            return
        try:
            self._source_image = Image.open(path)
            self._source_image.load()
        except Exception as exc:
            self.image_container.config(text="截图加载失败：%s" % exc, image="")
            return
        self.window.after(60, self.render_image)

    def on_image_area_resize(self, event=None):
        """窗口尺寸变化时按比例重绘图片（做个防抖，避免拖动时反复缩放）。

        尺寸直接取事件里的宽高——此时内部 Label 还没完成布局，
        winfo_width() 拿到的会是上一轮的旧值。
        """
        if event is not None:
            self._area = (event.width, event.height)
        if self._source_image is None:
            return
        if self._resize_job:
            self.window.after_cancel(self._resize_job)
        self._resize_job = self.window.after(120, self.render_image)

    def render_image(self):
        self._resize_job = None
        if self._source_image is None or not self.alive():
            return
        area_w, area_h = self._area
        if area_w <= 1 or area_h <= 1:
            area_w = self.image_container.winfo_width()
            area_h = self.image_container.winfo_height()
        avail_w = max(120, area_w - 18)
        avail_h = max(120, area_h - 18)
        width, height = self._source_image.size
        ratio = min(avail_w / width, avail_h / height, 2.0)
        size = (max(1, int(width * ratio)), max(1, int(height * ratio)))
        if self._photo is not None and size == getattr(self, "_photo_size", None):
            return          # 尺寸没变就不重复缩放
        self._photo_size = size
        resized = self._source_image.resize(size, Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(resized)
        self.image_container.config(image=self._photo, text="")

    # ------------------------------------------------------------ 答案读写

    def collect_answers(self):
        """从界面控件读出当前答案。"""
        if self.mode == "multi":
            return [key for key, var in self.answer_vars if var.get()]
        if self.mode == "single":
            value = self.answer_var.get()
            return [value] if value else []
        if self.mode == "text":
            content = self.subjective_text.get("1.0", tk.END).strip()
            return [content] if content else []
        return [entry.get().strip() for entry in self.answer_entries if entry.get().strip()]

    def apply_answers(self, answers):
        """把答案写回界面控件。"""
        if self.mode == "multi":
            for key, var in self.answer_vars:
                var.set(key in answers)
        elif self.mode == "single":
            if answers:
                self.answer_var.set(answers[0])
        elif self.mode == "text":
            self.subjective_text.delete("1.0", tk.END)
            if answers:
                self.subjective_text.insert(tk.END, str(answers[0]))
        else:
            for i, entry in enumerate(self.answer_entries):
                entry.delete(0, tk.END)
                if i < len(answers):
                    entry.insert(0, str(answers[i]))

    def set_status(self, text, tone="muted"):
        colors = {"muted": Theme.C["muted"], "success": Theme.C["success"],
                  "error": Theme.C["danger"], "warning": Theme.C["warning"]}
        self.status_label.config(text=text, foreground=colors.get(tone, Theme.C["muted"]))

    # ------------------------------------------------------------ 动作

    def on_save_click(self):
        if self.locked:
            return
        answers = self.collect_answers()
        if not answers:
            self.set_status("还没有填写答案", "warning")
            return
        self.problem["answers"] = answers
        if self.lesson:
            self.lesson.notify_update()
        elif self.parent_window:
            self.parent_window.refresh()
        self.set_status("答案已保存到本地，课上推送该题时会自动提交", "success")

    def on_submit_click(self):
        if self.locked or self.lesson is None:
            return
        answers = self.collect_answers()
        if not answers:
            self.set_status("还没有填写答案", "warning")
            return
        if not messagebox.askokcancel("确认提交",
                                      "确定把答案 %s 提交到雨课堂吗？\n提交后不可修改。" % "、".join(map(str, answers))):
            return
        self.problem["answers"] = answers
        self.submit_btn.state(["disabled"])
        self.set_status("正在提交……")

        def work():
            try:
                self.lesson.submit_problem(self.problem)
            except Exception as exc:
                self._ui(lambda: self._submit_failed(exc))
            else:
                self._ui(self._submit_ok)

        threading.Thread(target=work, daemon=True).start()

    def _submit_ok(self):
        self.locked = True
        self.set_status("提交成功，本题已锁定", "success")
        for widget in (self.save_btn, self.ai_btn):
            widget.state(["disabled"])
        if self.parent_window:
            self.parent_window.refresh()

    def _submit_failed(self, exc):
        self.submit_btn.state(["!disabled"])
        self.set_status("提交失败：%s" % exc, "error")

    def on_ai_answer_click(self):
        if self.locked:
            return
        key = (self.config.get("ai_config", {}).get("api_key") or "").strip()
        if not key:
            messagebox.showwarning("尚未配置 API Key",
                                   "请先回到主界面点击「设置」，填写 AI API Key 后再使用 AI 答题。")
            return
        image_path = self.problem.get("image", "")
        if not image_path or not os.path.exists(image_path):
            self.set_status("没有题目截图，无法使用 AI 答题", "warning")
            return

        self.ai_btn.state(["disabled"])
        self.set_status("AI 正在思考……")
        threading.Thread(target=self._call_ai_api, daemon=True).start()

    def _call_ai_api(self):
        from Scripts.AI import call_ai
        try:
            answers = call_ai(self.config, self.problem.get("image"))
        except Exception as exc:
            self._ui(lambda: self.set_status("AI 答题失败：%s" % exc, "error"))
        else:
            self._ui(lambda: self._on_ai_answer(answers))
        finally:
            self._ui(lambda: self.ai_btn.state(["!disabled"]))

    def _on_ai_answer(self, answers):
        if not answers:
            self.set_status("AI 未返回有效答案，可重试或手动作答", "warning")
            return
        self.apply_answers(answers)
        self.problem["answers"] = answers
        if self.lesson:
            self.lesson.notify_update()
        self.set_status("AI 答案：%s —— 请核对后点击「保存答案」或「提交到雨课堂」"
                        % "、".join(map(str, answers)), "success")

    # ------------------------------------------------------------ 杂项

    def _ui(self, func):
        """把回调丢回主线程执行。

        注意：这里不能调用 winfo_exists() 之类的 Tcl 接口——子线程碰 Tcl
        会抛 RuntimeError，之前被 except 吞掉，导致进度和完成回调全部丢失。
        """
        if self._closed:
            return
        try:
            self.window.after(0, func)
        except (tk.TclError, RuntimeError):
            pass

    def alive(self):
        """窗口是否还在。_closed 是纯 Python 标志，子线程里判断它不碰 Tcl。"""
        if self._closed:
            return False
        try:
            return bool(self.window.winfo_exists())
        except (tk.TclError, RuntimeError):
            return False

    def focus(self):
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def close(self):
        self._closed = True
        try:
            self.window.destroy()
        except tk.TclError:
            pass
