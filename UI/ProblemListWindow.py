# -*- coding: utf-8 -*-
"""题目列表窗口：总览一门课的所有题目，并可批量交给 AI 解答。"""
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox, ttk

from Scripts.Classes import format_answer, problem_type_name
from UI import Theme
from UI.ProblemDetailWindow import ProblemDetailWindow


class ProblemListWindow:
    """显示课程题目列表的窗口。"""

    def __init__(self, master, lesson, main_ui=None):
        self.lesson = lesson
        self.main_ui = main_ui
        self.config = getattr(main_ui, "config", None) or lesson.config
        self.detail_windows = {}
        self.solving = False
        self._closed = False
        self.cancel_flag = threading.Event()

        self.window = tk.Toplevel(master)
        self.window.title("%s - 题目列表" % lesson.lessonname)
        self.window.configure(bg=Theme.C["bg"])
        Theme.apply_icon(self.window)
        Theme.center(self.window, 940, 660)
        self.window.minsize(760, 480)

        self.create_ui()
        self.refresh()

        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda _: self.close())
        self.window.bind("<F5>", lambda _: self.refresh())

    # ------------------------------------------------------------ 界面

    def create_ui(self):
        c = Theme.C
        root = ttk.Frame(self.window)
        root.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)

        # --- 顶部：标题 + 统计
        head = ttk.Frame(root)
        head.pack(fill=tk.X)
        ttk.Label(head, text=self.lesson.lessonname, style="Section.TLabel").pack(side=tk.LEFT)
        self.count_badge = Theme.Badge(head, "0 题", "accent")
        self.count_badge.pack(side=tk.LEFT, padx=10)
        self.done_badge = Theme.Badge(head, "已提交 0", "success")
        self.done_badge.pack(side=tk.LEFT)

        ttk.Label(root, text="双击题目可查看大图、修改答案或单独让 AI 作答；已提交的题目会被锁定。",
                  style="Muted.TLabel").pack(anchor=tk.W, pady=(4, 12))

        # --- 工具栏
        bar = ttk.Frame(root)
        bar.pack(fill=tk.X, pady=(0, 10))
        self.solve_all_btn = ttk.Button(bar, text="✨  AI 解答全部未答题", style="Accent.TButton",
                                        command=self.on_solve_all_click)
        self.solve_all_btn.pack(side=tk.LEFT)
        self.cancel_btn = ttk.Button(bar, text="停止", command=self.on_cancel_click, width=8)
        self.detail_btn = ttk.Button(bar, text="查看选中题目", command=self.open_selected, width=14)
        self.detail_btn.pack(side=tk.LEFT, padx=8)
        ttk.Button(bar, text="刷新", command=self.refresh, width=8).pack(side=tk.LEFT)
        self.progress_label = ttk.Label(bar, text="", style="Muted.TLabel")
        self.progress_label.pack(side=tk.RIGHT)

        self.progress = ttk.Progressbar(root, mode="determinate")

        # --- 表格
        wrap = Theme.card(root)
        wrap.pack(fill=tk.BOTH, expand=True)

        columns = ("page", "type", "body", "answer", "state")
        self.tree = ttk.Treeview(wrap, columns=columns, show="headings", selectmode="browse")
        for key, text, width, anchor, stretch in (
                ("page", "页码", 70, tk.CENTER, False),
                ("type", "题型", 90, tk.CENTER, False),
                ("body", "题干", 380, tk.W, True),
                ("answer", "当前答案", 200, tk.W, False),
                ("state", "状态", 100, tk.CENTER, False)):
            self.tree.heading(key, text=text, anchor=anchor)
            self.tree.column(key, width=width, anchor=anchor, stretch=stretch)

        scrollbar = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=1, padx=(0, 1))
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.tree.tag_configure("odd", background=c["surface_alt"])
        self.tree.tag_configure("locked", foreground=c["faint"])
        self.tree.tag_configure("ready", foreground=c["success"])
        self.tree.tag_configure("pending", foreground=c["text"])

        self.tree.bind("<Double-Button-1>", lambda _: self.open_selected())
        self.tree.bind("<Return>", lambda _: self.open_selected())

        self.empty_hint = tk.Label(wrap, text="这门课还没有加载到题目\n老师放出课件后会自动出现",
                                   font=Theme.font(11), fg=c["faint"], bg=c["surface"],
                                   justify=tk.CENTER)

    # ------------------------------------------------------------ 数据刷新

    def refresh(self):
        """按当前题目数据重建表格。"""
        if not self.alive():
            return
        problems = self.lesson.snapshot_problems()
        self.problems = problems

        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())

        for idx, problem in enumerate(problems):
            locked = problem.get("result") is not None
            answer = format_answer(problem)
            if locked:
                state, tag = "已提交", "locked"
            elif answer:
                state, tag = "待提交", "ready"
            else:
                state, tag = "未作答", "pending"
            body = (problem.get("body") or "（无题干文字，见截图）").replace("\n", " ").strip()
            tags = [tag] + (["odd"] if idx % 2 else [])
            self.tree.insert("", "end", iid=str(idx), tags=tuple(tags),
                             values=(problem.get("page", "?"), problem_type_name(problem),
                                     body, answer or "—", state))

        for iid in selected:
            if self.tree.exists(iid):
                self.tree.selection_set(iid)

        total = len(problems)
        done = sum(1 for p in problems if p.get("result") is not None)
        pending = sum(1 for p in problems if p.get("result") is None and not (p.get("answers") or []))
        self.count_badge.set("%d 题" % total, "accent")
        self.done_badge.set("已提交 %d · 待解答 %d" % (done, pending),
                            "success" if pending == 0 else "warning")
        self.solve_all_btn.state(["disabled"] if (pending == 0 or self.solving) else ["!disabled"])

        if total:
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(relx=0.5, rely=0.45, anchor=tk.CENTER)

        for key, window in list(self.detail_windows.items()):
            if not window.alive():
                self.detail_windows.pop(key, None)

    # ------------------------------------------------------------ 交互

    def selected_problem(self):
        selection = self.tree.selection()
        if not selection:
            return None
        idx = int(selection[0])
        return self.problems[idx] if idx < len(self.problems) else None

    def open_selected(self):
        problem = self.selected_problem()
        if problem is None:
            messagebox.showinfo("提示", "请先在列表中选择一道题目")
            return
        key = str(problem.get("problemId"))
        existing = self.detail_windows.get(key)
        if existing and existing.alive():
            existing.focus()
            return
        self.detail_windows[key] = ProblemDetailWindow(self.window, problem, self.lesson, self)

    def _ensure_api_key(self):
        key = (self.config.get("ai_config", {}).get("api_key") or "").strip()
        if key:
            return True
        messagebox.showwarning("尚未配置 API Key",
                               "请先回到主界面点击「设置」，填写 AI API Key 后再使用 AI 解答。")
        return False

    def on_solve_all_click(self):
        if self.solving or not self._ensure_api_key():
            return
        targets = [p for p in self.problems
                   if p.get("result") is None and not (p.get("answers") or [])]
        if not targets:
            messagebox.showinfo("提示", "没有需要解答的题目")
            return

        self.solving = True
        self.cancel_flag.clear()
        self.solve_all_btn.state(["disabled"])
        self.detail_btn.state(["disabled"])
        self.cancel_btn.pack(side=tk.LEFT, padx=(0, 8), before=self.detail_btn)
        self.progress.pack(fill=tk.X, pady=(0, 10), before=self.tree.master)
        self.progress.configure(maximum=len(targets), value=0)
        self.progress_label.config(text="0 / %d" % len(targets))

        threading.Thread(target=self._solve_all_problems, args=(targets,), daemon=True).start()

    def on_cancel_click(self):
        self.cancel_flag.set()
        self.progress_label.config(text="正在停止……")

    def _solve_all_problems(self, targets):
        from Scripts.AI import call_ai

        total = len(targets)
        done = threading.Semaphore(0)
        counter = {"n": 0, "ok": 0, "fail": 0}
        lock = threading.Lock()

        def work(problem):
            if self.cancel_flag.is_set():
                return
            try:
                answers = call_ai(self.config, problem.get("image"))
                problem["answers"] = answers
                with lock:
                    counter["ok"] += 1
            except Exception as exc:
                with lock:
                    counter["fail"] += 1
                self._log("第%s页 AI 解答失败：%s" % (problem.get("page", "?"), exc), 4)
            finally:
                with lock:
                    counter["n"] += 1
                    n = counter["n"]
                self._ui(lambda: self._update_progress(n, total))

        workers = max(1, min(8, int(self.config.get("ai_config", {}).get("concurrency", 3))))
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(work, targets))
        except Exception as exc:
            self._ui(lambda: messagebox.showerror("错误", "AI 批量解答失败：%s" % exc))
        finally:
            self._ui(lambda: self._finish_solving(counter, total))

    def _update_progress(self, n, total):
        if not self.alive():
            return
        self.progress.configure(value=n)
        self.progress_label.config(text="%d / %d" % (n, total))
        self.refresh()

    def _finish_solving(self, counter, total):
        self.solving = False
        if not self.alive():
            return
        self.cancel_btn.pack_forget()
        self.progress.pack_forget()
        self.progress_label.config(text="")
        self.detail_btn.state(["!disabled"])
        self.refresh()

        if self.cancel_flag.is_set():
            messagebox.showinfo("已停止", "已停止 AI 解答，已完成 %d 道。" % counter["ok"])
        elif counter["fail"]:
            messagebox.showwarning("部分失败",
                                   "共 %d 道题，成功 %d 道，失败 %d 道。\n失败原因见主界面的系统消息。"
                                   % (total, counter["ok"], counter["fail"]))
        else:
            messagebox.showinfo("完成", "AI 已解答全部 %d 道题目，可逐题核对后提交。" % counter["ok"])

    # ------------------------------------------------------------ 杂项

    def _log(self, message, level=0):
        if self.main_ui:
            self.main_ui.add_message("%s %s" % (self.lesson.lessonname, message), level)

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
        self.cancel_flag.set()
        for window in list(self.detail_windows.values()):
            window.close()
        self.detail_windows.clear()
        try:
            self.window.destroy()
        except tk.TclError:
            pass
