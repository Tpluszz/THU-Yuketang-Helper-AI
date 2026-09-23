# -*- coding: utf-8 -*-
"""AI 答案提交前的确认框（ai_confirm 模式用）。

课上弹出来，带倒计时；超时默认「不提交」，避免人不在电脑前时误交。
"""
import os
import tkinter as tk
from tkinter import ttk

from UI import Theme


class ConfirmAnswerDialog:
    def __init__(self, master, lesson, problem, answers, timeout, on_decided):
        self.on_decided = on_decided
        self.answers = answers
        self.problem = problem
        self._decided = False
        self._left = max(1, int(timeout))
        self._thumb = None

        self.top = tk.Toplevel(master)
        self.top.title("确认提交答案")
        self.top.configure(bg=Theme.C["bg"])
        self.top.resizable(False, False)
        Theme.apply_icon(self.top)

        self.build(lesson)
        Theme.center(self.top, 460, 520 if self._thumb else 320)

        self.top.protocol("WM_DELETE_WINDOW", lambda: self.decide(False))
        self.top.bind("<Escape>", lambda _: self.decide(False))
        self.top.bind("<Return>", lambda _: self.decide(True))
        # 课上要抢时间，直接把窗口顶到最前并聚焦到「提交」
        self.top.attributes("-topmost", True)
        self.top.lift()
        self.top.after(50, self.submit_btn.focus_set)
        self.tick()

    def build(self, lesson):
        root = ttk.Frame(self.top)
        root.pack(fill=tk.BOTH, expand=True, padx=18, pady=16)

        ttk.Label(root, text="AI 已作答，确认提交吗？",
                  font=Theme.font(14, "bold")).pack(anchor=tk.W)
        ttk.Label(root, text="%s · 第 %s 页" % (lesson.lessonname, self.problem.get("page", "?")),
                  style="Muted.TLabel").pack(anchor=tk.W, pady=(4, 12))

        body = (self.problem.get("body") or "").strip().replace("\n", " ")
        if body:
            ttk.Label(root, text=body[:120] + ("…" if len(body) > 120 else ""),
                      style="Muted.TLabel", wraplength=410,
                      justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 10))

        card = Theme.card(root)
        card.pack(fill=tk.X, pady=(0, 12))
        tk.Label(card, text="AI 答案", font=Theme.font(10), fg=Theme.C["muted"],
                 bg=Theme.C["surface"]).pack(anchor=tk.W, padx=12, pady=(10, 2))
        tk.Label(card, text="、".join(str(a) for a in self.answers) or "（空）",
                 font=Theme.font(15, "bold"), fg=Theme.C["accent"], bg=Theme.C["surface"],
                 wraplength=400, justify=tk.LEFT).pack(anchor=tk.W, padx=12, pady=(0, 12))

        self._add_thumbnail(root)

        self.count_label = ttk.Label(root, text="", style="Muted.TLabel")
        self.count_label.pack(anchor=tk.W, pady=(4, 10))

        row = ttk.Frame(root)
        row.pack(fill=tk.X)
        self.submit_btn = ttk.Button(row, text="提交", style="Accent.TButton", width=12,
                                     command=lambda: self.decide(True))
        self.submit_btn.pack(side=tk.RIGHT)
        ttk.Button(row, text="不提交", width=10,
                   command=lambda: self.decide(False)).pack(side=tk.RIGHT, padx=8)

    def _add_thumbnail(self, parent):
        path = self.problem.get("image", "")
        if not path or not os.path.exists(path):
            return
        try:
            from PIL import Image, ImageTk
            image = Image.open(path)
            image.thumbnail((410, 200), Image.LANCZOS)
            self._thumb = ImageTk.PhotoImage(image)
        except Exception:
            return
        holder = Theme.card(parent)
        holder.pack(fill=tk.X, pady=(0, 10))
        tk.Label(holder, image=self._thumb, bg=Theme.C["surface"]).pack(padx=1, pady=1)

    def tick(self):
        if self._decided:
            return
        if self._left <= 0:
            self.decide(False, timed_out=True)
            return
        self.count_label.config(text="%d 秒后自动放弃提交（可稍后在题目列表里手动提交）" % self._left)
        self._left -= 1
        self.top.after(1000, self.tick)

    def decide(self, ok, timed_out=False):
        if self._decided:
            return
        self._decided = True
        try:
            self.top.destroy()
        except tk.TclError:
            pass
        try:
            self.on_decided(ok)
        except Exception:
            pass
