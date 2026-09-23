# -*- coding: utf-8 -*-
"""设置对话框：答题策略、AI 服务、弹幕与外观。"""
import os
import platform
import subprocess
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from Scripts.AI import DEFAULT_BASE_URL, DEFAULT_MODEL
from Scripts.Utils import get_config_dir, save_config
from UI import Theme

API_KEY_HELP = "https://help.aliyun.com/zh/model-studio/get-api-key"


class ConfigDialog:
    def __init__(self, parent, main_window):
        self.parent = parent
        self.main_window = main_window
        self.config = dict(main_window.config)
        self.saved = False
        self._closed = False
        self.theme_changed = False
        self._original_theme = self.config.get("ui_theme", "auto")

        self.top = tk.Toplevel(parent)
        self.top.title("设置")
        self.top.configure(bg=Theme.C["bg"])
        self.top.resizable(True, True)
        self.top.minsize(540, 520)
        Theme.apply_icon(self.top)

        self.create_ui()
        self.load_config()
        self.size_to_content()

        self.top.protocol("WM_DELETE_WINDOW", self.close_window)
        self.top.bind("<Escape>", lambda _: self.close_window())
        self.top.transient(parent)
        self.top.grab_set()

    # ------------------------------------------------------------ 界面

    def create_ui(self):
        root = ttk.Frame(self.top)
        root.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)

        # 底部按钮先 pack，保证它永远留在窗口里，不会被内容挤掉
        footer = ttk.Frame(root)
        footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(14, 0))

        notebook = ttk.Notebook(root)
        notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        notebook.add(self.create_answer_tab(notebook), text="  自动答题  ")
        notebook.add(self.create_ai_tab(notebook), text="  AI 服务  ")
        notebook.add(self.create_misc_tab(notebook), text="  弹幕与外观  ")

        ttk.Button(footer, text="打开配置目录", style="Link.TButton",
                   command=self.open_config_dir).pack(side=tk.LEFT)
        ttk.Button(footer, text="取消", command=self.close_window, width=8).pack(side=tk.RIGHT)
        ttk.Button(footer, text="保存设置", style="Accent.TButton",
                   command=self.save_config, width=10).pack(side=tk.RIGHT, padx=8)

    def size_to_content(self):
        """按最高的那一页定尺寸，保证每个标签页都装得下，同时不超出屏幕。"""
        self.top.update_idletasks()
        width = max(580, self.top.winfo_reqwidth())
        height = self.top.winfo_reqheight()
        height = min(height, int(self.top.winfo_screenheight() * 0.85))
        Theme.center(self.top, width, height)

    @staticmethod
    def open_config_dir():
        """在系统文件管理器里打开配置 / 截图目录。"""
        path = get_config_dir()
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            webbrowser.open("file://" + path)

    def _tab(self, notebook):
        frame = ttk.Frame(notebook, style="Surface.TFrame", padding=18)
        return frame

    def create_answer_tab(self, notebook):
        tab = self._tab(notebook)

        self.auto_answer_var = tk.BooleanVar()
        ttk.Checkbutton(tab, text="启用自动答题（课上推送题目时自动提交已保存的答案）",
                        variable=self.auto_answer_var, style="Surface.TCheckbutton",
                        command=self.toggle_answer_settings).pack(anchor=tk.W)

        self.answer_box = ttk.Frame(tab, style="Surface.TFrame")
        self.answer_box.pack(fill=tk.X, padx=(22, 0), pady=(10, 0))

        ttk.Label(self.answer_box, text="提交延迟", style="SurfaceSection.TLabel").pack(anchor=tk.W)
        ttk.Label(self.answer_box, text="适当延迟可以让答题时间看起来更自然。",
                  style="SurfaceMuted.TLabel").pack(anchor=tk.W, pady=(2, 8))

        self.delay_type_var = tk.IntVar(value=1)
        ttk.Radiobutton(self.answer_box, text="随机延迟（推荐）", variable=self.delay_type_var,
                        value=1, style="Surface.TRadiobutton",
                        command=self.toggle_delay_custom).pack(anchor=tk.W)
        ttk.Radiobutton(self.answer_box, text="固定延迟", variable=self.delay_type_var,
                        value=2, style="Surface.TRadiobutton",
                        command=self.toggle_delay_custom).pack(anchor=tk.W, pady=(4, 0))

        self.delay_custom_frame = ttk.Frame(self.answer_box, style="Surface.TFrame")
        self.delay_custom_frame.pack(fill=tk.X, padx=(22, 0), pady=(6, 0))
        ttk.Label(self.delay_custom_frame, text="延迟秒数",
                  style="SurfaceMuted.TLabel").pack(side=tk.LEFT)
        self.custom_time_var = tk.IntVar(value=0)
        ttk.Spinbox(self.delay_custom_frame, from_=0, to=300, width=8,
                    textvariable=self.custom_time_var).pack(side=tk.LEFT, padx=10)

        ttk.Separator(self.answer_box).pack(fill=tk.X, pady=16)

        self.auto_ai_var = tk.BooleanVar()
        ttk.Checkbutton(self.answer_box, text="遇到没有答案的新题目时，自动调用 AI 解答后再提交",
                        variable=self.auto_ai_var, style="Surface.TCheckbutton").pack(anchor=tk.W)
        ttk.Label(self.answer_box,
                  text="关闭时只会提交你事先保存好的答案；开启后会即时消耗 AI 额度，\n"
                       "且来不及人工核对，请按需选择。",
                  style="SurfaceMuted.TLabel", justify=tk.LEFT).pack(anchor=tk.W, padx=(22, 0), pady=(4, 0))
        return tab

    def create_ai_tab(self, notebook):
        tab = self._tab(notebook)

        ttk.Label(tab, text="服务提供方", style="SurfaceSection.TLabel").pack(anchor=tk.W)
        self.ai_provider_var = tk.StringVar(value="glm")
        ttk.Radiobutton(tab, text="GLM（Anthropic 兼容接口）", variable=self.ai_provider_var,
                        value="glm", style="Surface.TRadiobutton",
                        command=self.toggle_provider).pack(anchor=tk.W, pady=(6, 0))
        ttk.Radiobutton(tab, text="通义千问 Qwen（dashscope）", variable=self.ai_provider_var,
                        value="qwen", style="Surface.TRadiobutton",
                        command=self.toggle_provider).pack(anchor=tk.W, pady=(4, 0))

        ttk.Separator(tab).pack(fill=tk.X, pady=14)

        ttk.Label(tab, text="API Key", style="SurfaceSection.TLabel").pack(anchor=tk.W)
        key_row = ttk.Frame(tab, style="Surface.TFrame")
        key_row.pack(fill=tk.X, pady=(6, 4))
        self.ai_key_var = tk.StringVar()
        self.ai_key_entry = ttk.Entry(key_row, textvariable=self.ai_key_var, show="•")
        self.ai_key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.show_key_var = tk.BooleanVar()
        ttk.Checkbutton(key_row, text="显示", variable=self.show_key_var,
                        style="Surface.TCheckbutton",
                        command=self.toggle_key_visibility).pack(side=tk.LEFT, padx=10)

        link = ttk.Button(tab, text="如何获取 API Key？", style="SurfaceLink.TButton",
                          command=lambda: webbrowser.open(API_KEY_HELP))
        link.pack(anchor=tk.W)

        self.glm_box = ttk.Frame(tab, style="Surface.TFrame")
        self.glm_box.pack(fill=tk.X, pady=(14, 0))

        ttk.Label(self.glm_box, text="接口地址（Base URL）",
                  style="SurfaceSection.TLabel").pack(anchor=tk.W)
        self.ai_base_url_var = tk.StringVar(value=DEFAULT_BASE_URL)
        ttk.Entry(self.glm_box, textvariable=self.ai_base_url_var).pack(fill=tk.X, pady=(6, 12))

        ttk.Label(self.glm_box, text="模型名称", style="SurfaceSection.TLabel").pack(anchor=tk.W)
        self.ai_model_var = tk.StringVar(value=DEFAULT_MODEL)
        ttk.Entry(self.glm_box, textvariable=self.ai_model_var).pack(fill=tk.X, pady=(6, 12))

        self.ai_thinking_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.glm_box, text="启用思考模式（正确率更高，但更慢、更费 token）",
                        variable=self.ai_thinking_var,
                        style="Surface.TCheckbutton").pack(anchor=tk.W)

        ttk.Separator(tab).pack(fill=tk.X, pady=14)

        conc_row = ttk.Frame(tab, style="Surface.TFrame")
        conc_row.pack(fill=tk.X)
        ttk.Label(conc_row, text="批量解题并发数", style="Surface.TLabel").pack(side=tk.LEFT)
        self.concurrency_var = tk.IntVar(value=3)
        ttk.Spinbox(conc_row, from_=1, to=8, width=6,
                    textvariable=self.concurrency_var).pack(side=tk.LEFT, padx=10)
        ttk.Label(conc_row, text="过高容易被限流", style="SurfaceMuted.TLabel").pack(side=tk.LEFT)

        test_row = ttk.Frame(tab, style="Surface.TFrame")
        test_row.pack(fill=tk.X, pady=(16, 0))
        self.test_btn = ttk.Button(test_row, text="测试连接", command=self.on_test_connection, width=10)
        self.test_btn.pack(side=tk.LEFT)
        self.test_label = ttk.Label(test_row, text="", style="SurfaceMuted.TLabel", wraplength=340)
        self.test_label.pack(side=tk.LEFT, padx=12)
        return tab

    def create_misc_tab(self, notebook):
        tab = self._tab(notebook)

        ttk.Label(tab, text="弹幕", style="SurfaceSection.TLabel").pack(anchor=tk.W)
        self.danmu_on_var = tk.BooleanVar()
        ttk.Checkbutton(tab, text="启用自动跟发弹幕", variable=self.danmu_on_var,
                        style="Surface.TCheckbutton",
                        command=self.toggle_danmu_settings).pack(anchor=tk.W, pady=(6, 0))

        self.danmu_box = ttk.Frame(tab, style="Surface.TFrame")
        self.danmu_box.pack(fill=tk.X, padx=(22, 0), pady=(8, 0))
        ttk.Label(self.danmu_box, text="同一条弹幕被多少人发过之后才跟发",
                  style="SurfaceMuted.TLabel").pack(anchor=tk.W)
        self.danmu_spinbox_var = tk.IntVar(value=5)
        ttk.Spinbox(self.danmu_box, from_=1, to=100, width=8,
                    textvariable=self.danmu_spinbox_var).pack(anchor=tk.W, pady=6)

        ttk.Separator(tab).pack(fill=tk.X, pady=18)

        ttk.Label(tab, text="外观", style="SurfaceSection.TLabel").pack(anchor=tk.W)
        ttk.Label(tab, text="修改后需要重新启动程序才会生效。",
                  style="SurfaceMuted.TLabel").pack(anchor=tk.W, pady=(2, 8))
        self.theme_var = tk.StringVar(value="auto")
        for value, text in (("auto", "跟随系统"), ("light", "浅色"), ("dark", "深色")):
            ttk.Radiobutton(tab, text=text, variable=self.theme_var, value=value,
                            style="Surface.TRadiobutton").pack(anchor=tk.W, pady=2)
        return tab

    # ------------------------------------------------------------ 联动

    def toggle_key_visibility(self):
        self.ai_key_entry.config(show="" if self.show_key_var.get() else "•")

    def toggle_provider(self):
        state = ["!disabled"] if self.ai_provider_var.get() == "glm" else ["disabled"]
        for child in self.glm_box.winfo_children():
            try:
                child.state(state)
            except (AttributeError, tk.TclError):
                pass

    def _set_state(self, container, enabled):
        """递归启用/禁用一组控件；纯文本标签只改颜色，避免 clam 主题画出难看的底色。"""
        for child in container.winfo_children():
            if isinstance(child, ttk.Label):
                child.configure(foreground=Theme.C["muted"] if enabled else Theme.C["faint"])
            else:
                try:
                    child.state(["!disabled"] if enabled else ["disabled"])
                except (AttributeError, tk.TclError):
                    pass
            if child.winfo_children():
                self._set_state(child, enabled)

    def toggle_danmu_settings(self):
        self._set_state(self.danmu_box, self.danmu_on_var.get())

    def toggle_answer_settings(self):
        self._set_state(self.answer_box, self.auto_answer_var.get())
        self.toggle_delay_custom()

    def toggle_delay_custom(self):
        enabled = self.auto_answer_var.get() and self.delay_type_var.get() == 2
        self._set_state(self.delay_custom_frame, enabled)

    # ------------------------------------------------------------ 读写配置

    def load_config(self):
        self.danmu_on_var.set(self.config.get("auto_danmu", True))
        self.danmu_spinbox_var.set(self.config.get("danmu_config", {}).get("danmu_limit", 5))

        answer_config = self.config.get("answer_config", {})
        self.auto_answer_var.set(self.config.get("auto_answer", True))
        self.auto_ai_var.set(answer_config.get("auto_ai", False))
        delay = answer_config.get("answer_delay", {})
        self.delay_type_var.set(delay.get("type", 1))
        self.custom_time_var.set(delay.get("custom", {}).get("time", 0))

        ai_config = self.config.get("ai_config", {})
        self.ai_provider_var.set(ai_config.get("provider", "glm"))
        self.ai_base_url_var.set(ai_config.get("base_url", DEFAULT_BASE_URL))
        self.ai_model_var.set(ai_config.get("model", DEFAULT_MODEL))
        self.ai_key_var.set(ai_config.get("api_key", ""))
        self.ai_thinking_var.set(ai_config.get("enable_thinking", True))
        self.concurrency_var.set(ai_config.get("concurrency", 3))

        self.theme_var.set(self.config.get("ui_theme", "auto"))

        self.toggle_danmu_settings()
        self.toggle_answer_settings()
        self.toggle_provider()

    def _read_ai_config(self):
        return {
            "provider": self.ai_provider_var.get(),
            "api_key": self.ai_key_var.get().strip(),
            "base_url": self.ai_base_url_var.get().strip() or DEFAULT_BASE_URL,
            "model": self.ai_model_var.get().strip() or DEFAULT_MODEL,
            "enable_thinking": self.ai_thinking_var.get(),
            "concurrency": max(1, min(8, self._safe_int(self.concurrency_var, 3))),
        }

    @staticmethod
    def _safe_int(var, fallback):
        try:
            return int(var.get())
        except (tk.TclError, ValueError):
            return fallback

    def on_test_connection(self):
        from Scripts.AI import test_connection

        ai_config = self._read_ai_config()
        self.test_btn.state(["disabled"])
        self.test_label.config(text="正在测试……", foreground=Theme.C["muted"])

        def work():
            try:
                message = test_connection(ai_config)
            except Exception as exc:
                self._ui(lambda: self.test_label.config(text="✗ %s" % exc,
                                                        foreground=Theme.C["danger"]))
            else:
                self._ui(lambda: self.test_label.config(text="✓ %s" % message,
                                                        foreground=Theme.C["success"]))
            finally:
                self._ui(lambda: self.test_btn.state(["!disabled"]))

        threading.Thread(target=work, daemon=True).start()

    def _ui(self, func):
        """把回调丢回主线程；子线程里不碰 Tcl 接口。"""
        if self._closed:
            return
        try:
            self.top.after(0, func)
        except (tk.TclError, RuntimeError):
            pass

    def save_config(self):
        self.config["auto_danmu"] = self.danmu_on_var.get()
        self.config["danmu_config"] = {
            "danmu_limit": max(1, self._safe_int(self.danmu_spinbox_var, 5)),
        }
        self.config["auto_answer"] = self.auto_answer_var.get()
        self.config["answer_config"] = {
            "answer_delay": {
                "type": self.delay_type_var.get(),
                "custom": {"time": max(0, self._safe_int(self.custom_time_var, 0))},
            },
            "auto_ai": self.auto_ai_var.get(),
        }
        self.config["ai_config"] = self._read_ai_config()
        self.config["ui_theme"] = self.theme_var.get()

        try:
            save_config(self.config)
        except Exception as exc:
            messagebox.showerror("保存失败", "无法写入配置文件：%s" % exc, parent=self.top)
            return

        # 让正在监听的课程立刻用上新配置
        self.main_window.config.clear()
        self.main_window.config.update(self.config)

        self.saved = True
        self.theme_changed = self.config["ui_theme"] != self._original_theme
        self.close_window()

    def close_window(self):
        self._closed = True
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        self.top.destroy()
