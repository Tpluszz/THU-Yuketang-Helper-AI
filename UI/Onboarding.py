# -*- coding: utf-8 -*-
"""上手清单：第一次打开时引导走完必要的几步，之后也能随时从主界面打开。"""
import tkinter as tk
from tkinter import ttk

from Scripts.AI import PROVIDERS, normalize_provider
from Scripts.Utils import ANSWER_MODES, migrate_answer_mode, save_config
from UI import Theme

MODE_TEXT = {
    "notify":     ("只提示我", "推题时提醒你，全部自己作答"),
    "saved":      ("只交已保存的答案", "你提前填好的答案会自动提交；没答案的题只提醒"),
    "ai_confirm": ("AI 解答，问过我再交", "AI 答完弹窗给你过目，同意才提交（推荐）"),
    "ai_auto":    ("AI 解答并直接交", "全自动，来不及人工核对"),
}


def ai_ready(config):
    ai = (config or {}).get("ai_config", {})
    provider = normalize_provider(ai.get("provider"))
    if not (ai.get("api_key") or "").strip():
        return False
    if PROVIDERS[provider]["needs_url"] and not (ai.get("base_url") or "").strip():
        return False
    return bool((ai.get("model") or "").strip()) or provider == "qwen"


class OnboardingDialog:
    def __init__(self, main):
        self.main = main
        self.top = tk.Toplevel(main.master)
        self.top.title("上手清单")
        self.top.configure(bg=Theme.C["bg"])
        self.top.resizable(False, False)
        Theme.apply_icon(self.top)
        self.top.transient(main.master)

        self.rows = {}
        self.create_ui()
        self.refresh()
        Theme.center(self.top, 560, self.top.winfo_reqheight() + 10)
        self.top.protocol("WM_DELETE_WINDOW", self.skip)
        self.top.bind("<Escape>", lambda _: self.skip())
        self._tick()

    # ------------------------------------------------------------ 界面

    def create_ui(self):
        c = Theme.C
        root = ttk.Frame(self.top)
        root.pack(fill=tk.BOTH, expand=True, padx=22, pady=18)

        ttk.Label(root, text="几步就能用起来", font=Theme.font(15, "bold")).pack(anchor=tk.W)
        ttk.Label(root, text="做完前两步就能上课用；后两步随时可以在「设置」里改。",
                  style="Muted.TLabel").pack(anchor=tk.W, pady=(4, 14))

        card = Theme.card(root)
        card.pack(fill=tk.X)
        inner = tk.Frame(card, bg=c["surface"])
        inner.pack(fill=tk.X, padx=16, pady=8)

        self._step(inner, "login", "1", "登录雨课堂", "用微信扫码，程序才能帮你签到和收题",
                   "扫码登录", self.do_login)
        self._sep(inner)
        self._step(inner, "ai", "2", "配置 AI", "填接口地址、模型和 API Key，AI 才能帮你解题",
                   "去设置", self.do_ai)
        self._sep(inner)

        # 第 3 步：答题方式直接在这里选
        head = self._step(inner, "mode", "3", "选择答题方式", "老师推题的时候，程序替你做到哪一步",
                          None, None)
        self.mode_var = tk.StringVar(
            value=migrate_answer_mode(dict(self.main.config))["answer_config"].get("mode", "ai_confirm"))
        box = tk.Frame(inner, bg=c["surface"])
        box.pack(fill=tk.X, padx=(34, 0), pady=(0, 6))
        for key in ANSWER_MODES:
            title, desc = MODE_TEXT[key]
            ttk.Radiobutton(box, text="%s —— %s" % (title, desc), value=key,
                            variable=self.mode_var, style="Surface.TRadiobutton").pack(anchor=tk.W)
        self._sep(inner)

        self._step(inner, "auto", "4", "打开程序就开始监听", "免得每次上课前还要手动点",
                   None, None)
        # 第一次上手时推荐开启；已经看过清单的人按其当前设置显示
        onboarded = self.main.config.get("onboarded")
        self.auto_var = tk.BooleanVar(
            value=self.main.config.get("auto_monitor", False) if onboarded else True)
        ttk.Checkbutton(inner, text="打开程序时自动开始监听（推荐）", variable=self.auto_var,
                        style="Surface.TCheckbutton").pack(anchor=tk.W, padx=(34, 0), pady=(0, 6))

        footer = ttk.Frame(root)
        footer.pack(fill=tk.X, pady=(16, 0))
        self.hint = ttk.Label(footer, text="", style="Muted.TLabel")
        self.hint.pack(side=tk.LEFT)
        ttk.Button(footer, text="以后再说", command=self.skip, width=9).pack(side=tk.RIGHT)
        self.finish_btn = ttk.Button(footer, text="完成", style="Accent.TButton",
                                     command=self.finish, width=12)
        self.finish_btn.pack(side=tk.RIGHT, padx=8)

    def _sep(self, parent):
        tk.Frame(parent, bg=Theme.C["border"], height=1).pack(fill=tk.X, pady=6)

    def _step(self, parent, key, num, title, desc, action_text, action):
        c = Theme.C
        row = tk.Frame(parent, bg=c["surface"])
        row.pack(fill=tk.X, pady=4)
        mark = tk.Label(row, text=num, width=2, font=Theme.font(12, "bold"),
                        bg=c["accent_soft"], fg=c["accent"])
        mark.pack(side=tk.LEFT, padx=(0, 12), ipady=2)
        text = tk.Frame(row, bg=c["surface"])
        text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(text, text=title, font=Theme.font(12, "bold"), bg=c["surface"],
                 fg=c["text"], anchor=tk.W).pack(fill=tk.X)
        status = tk.Label(text, text=desc, font=Theme.font(10), bg=c["surface"],
                          fg=c["muted"], anchor=tk.W)
        status.pack(fill=tk.X)
        button = None
        if action_text:
            button = ttk.Button(row, text=action_text, command=action, width=9)
            button.pack(side=tk.RIGHT)
        self.rows[key] = (mark, status, button, num, desc)
        return row

    # ------------------------------------------------------------ 状态

    def step_done(self):
        state = self.main.login_state
        return {
            "login": state == "ok",
            "login_pending": state == "checking",
            "ai": ai_ready(self.main.config),
        }

    def refresh(self):
        c = Theme.C
        done = self.step_done()
        for key in ("login", "ai"):
            mark, status, button, num, desc = self.rows[key]
            if done[key]:
                mark.config(text="✓", bg=c["success_soft"], fg=c["success"])
                extra = ("已登录 · %s" % self.main.user_name) if key == "login" else "已配置"
                status.config(text=extra, fg=c["success"])
                if button:
                    button.config(text="重新登录" if key == "login" else "修改")
            else:
                mark.config(text=num, bg=c["accent_soft"], fg=c["accent"])
                if key == "login" and done["login_pending"]:
                    status.config(text="正在检查登录……", fg=c["muted"])
                else:
                    status.config(text=desc, fg=c["muted"])
        if done["login"] and done["ai"]:
            self.hint.config(text="必要的步骤都完成了", foreground=c["success"])
            self.finish_btn.config(text="完成并开始监听")
        else:
            left = [n for n, k in (("登录", "login"), ("配置 AI", "ai")) if not done[k]]
            self.hint.config(text="还差：%s" % "、".join(left), foreground=c["muted"])
            self.finish_btn.config(text="完成")

    def _tick(self):
        """登录状态是后台异步确认的，清单开着时每秒同步一次。"""
        try:
            if not self.top.winfo_exists():
                return
        except tk.TclError:
            return
        self.refresh()
        self.top.after(1000, self._tick)

    # ------------------------------------------------------------ 动作

    def do_login(self):
        self.top.grab_release()
        self.main.show_login()
        self.refresh()
        self.top.lift()

    def do_ai(self):
        self.main.show_config(tab="ai")
        self.refresh()
        self.top.lift()

    def _save(self):
        answer = self.main.config.setdefault("answer_config", {})
        answer["mode"] = self.mode_var.get()
        migrate_answer_mode(self.main.config)
        self.main.config["auto_monitor"] = self.auto_var.get()
        self.main.config["onboarded"] = True
        save_config(self.main.config)

    def finish(self):
        self._save()
        done = self.step_done()
        self.top.destroy()
        self.main.refresh_account_state()
        if done["login"] and done["ai"] and not self.main.is_active and not self.main.test_mode:
            self.main.toggle_monitor()

    def skip(self):
        # 跳过也记下来，免得每次打开都弹；主界面随时能再打开
        self.main.config["onboarded"] = True
        try:
            save_config(self.main.config)
        except Exception:
            pass
        self.top.destroy()
