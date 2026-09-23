# -*- coding: utf-8 -*-
"""统一的视觉主题：配色、字体、ttk 样式与常用小部件。

所有窗口都通过这里取色和取字体，保证整体观感一致，
并且在 macOS / Windows / Linux 上都能拿到合适的中文字体。
"""
import os
import platform
import subprocess
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ---------------------------------------------------------------- 配色

LIGHT = {
    "bg":          "#F4F5F7",   # 窗口底色
    "surface":     "#FFFFFF",   # 卡片
    "surface_alt": "#FAFAFB",   # 斑马纹/次级卡片
    "border":      "#E1E4EA",
    "text":        "#1F2328",
    "muted":       "#6B7280",
    "faint":       "#9AA1AC",
    "accent":      "#7A1F8C",   # 清华紫
    "accent_hi":   "#93309F",
    "accent_lo":   "#5E1469",
    "accent_soft": "#F3E9F6",
    "success":     "#15803D",
    "success_soft": "#E7F5EC",
    "warning":     "#B45309",
    "warning_soft": "#FDF3E3",
    "danger":      "#C0392B",
    "danger_soft": "#FCEBE9",
    "info":        "#2563EB",
    "info_soft":   "#EAF0FE",
    "header":      "#241B2B",
    "header_text": "#FFFFFF",
    "header_sub":  "#B9AEC2",
    "disabled":    "#F0F1F3",
}

DARK = {
    "bg":          "#1B1D21",
    "surface":     "#24272C",
    "surface_alt": "#2A2E34",
    "border":      "#383C44",
    "text":        "#E8EAED",
    "muted":       "#9BA3AE",
    "faint":       "#767D87",
    "accent":      "#C07BD0",
    "accent_hi":   "#D094DD",
    "accent_lo":   "#A45CB4",
    "accent_soft": "#38263D",
    "success":     "#5DD48B",
    "success_soft": "#1E3227",
    "warning":     "#E0A35A",
    "warning_soft": "#33291A",
    "danger":      "#F08579",
    "danger_soft": "#3A2320",
    "info":        "#7FA9F5",
    "info_soft":   "#1F2937",
    "header":      "#14161A",
    "header_text": "#F5F5F7",
    "header_sub":  "#8C939E",
    "disabled":    "#2C3037",
}

# 当前生效的配色，由 init() 填充
C = dict(LIGHT)

# ---------------------------------------------------------------- 字体

_FONT_CANDIDATES = {
    "Darwin":  ["PingFang SC", "Hiragino Sans GB", "STHeiti", "Heiti SC"],
    "Windows": ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei"],
    "Linux":   ["Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei", "DejaVu Sans"],
}
_MONO_CANDIDATES = {
    "Darwin":  ["SF Mono", "Menlo", "Monaco"],
    "Windows": ["Cascadia Mono", "Consolas", "Courier New"],
    "Linux":   ["JetBrains Mono", "DejaVu Sans Mono", "Monospace"],
}

UI_FAMILY = "TkDefaultFont"
MONO_FAMILY = "TkFixedFont"


def _pick_family(candidates):
    try:
        available = {name.lower() for name in tkfont.families()}
    except Exception:
        return None
    for name in candidates:
        if name.lower() in available:
            return name
    return None


def font(size=10, weight="normal", mono=False):
    """取一个当前平台可用的字体元组。"""
    return (MONO_FAMILY if mono else UI_FAMILY, size, weight)


# ---------------------------------------------------------------- 主题选择

def _system_prefers_dark():
    if platform.system() != "Darwin":
        return False
    try:
        out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                             capture_output=True, text=True, timeout=2)
        return "dark" in out.stdout.lower()
    except Exception:
        return False


def resolve_mode(preference="auto"):
    if preference == "dark":
        return "dark"
    if preference == "light":
        return "light"
    return "dark" if _system_prefers_dark() else "light"


# ---------------------------------------------------------------- 初始化

def init(root, preference="auto"):
    """在根窗口上安装主题，返回实际使用的模式（light/dark）。"""
    global C, UI_FAMILY, MONO_FAMILY

    mode = resolve_mode(preference)
    C.clear()
    C.update(DARK if mode == "dark" else LIGHT)

    picked = _pick_family(_FONT_CANDIDATES.get(platform.system(), _FONT_CANDIDATES["Linux"]))
    if picked:
        UI_FAMILY = picked
    picked_mono = _pick_family(_MONO_CANDIDATES.get(platform.system(), _MONO_CANDIDATES["Linux"]))
    if picked_mono:
        MONO_FAMILY = picked_mono

    # 同步 Tk 的内建字体，让 messagebox 等系统控件也跟着变
    for name, size in (("TkDefaultFont", 12), ("TkTextFont", 12), ("TkMenuFont", 12),
                       ("TkHeadingFont", 12), ("TkTooltipFont", 11)):
        try:
            tkfont.nametofont(name).configure(family=UI_FAMILY, size=size)
        except Exception:
            pass

    root.configure(bg=C["bg"])
    style = ttk.Style(root)
    try:
        style.theme_use("clam")   # clam 允许完全自定义配色，跨平台表现一致
    except tk.TclError:
        pass
    _configure_styles(style)
    return mode


def _configure_styles(style):
    c = C
    base = font(11)

    style.configure(".", background=c["bg"], foreground=c["text"],
                    fieldbackground=c["surface"], font=base, borderwidth=0)

    # --- 容器
    style.configure("TFrame", background=c["bg"])
    style.configure("Surface.TFrame", background=c["surface"])
    style.configure("Header.TFrame", background=c["header"])
    style.configure("Card.TFrame", background=c["surface"], relief="solid",
                    borderwidth=1, bordercolor=c["border"])

    # --- 文本
    style.configure("TLabel", background=c["bg"], foreground=c["text"])
    style.configure("Surface.TLabel", background=c["surface"], foreground=c["text"])
    style.configure("Muted.TLabel", background=c["bg"], foreground=c["muted"], font=font(10))
    style.configure("SurfaceMuted.TLabel", background=c["surface"], foreground=c["muted"], font=font(10))
    style.configure("Title.TLabel", background=c["header"], foreground=c["header_text"],
                    font=font(16, "bold"))
    style.configure("Subtitle.TLabel", background=c["header"], foreground=c["header_sub"],
                    font=font(10))
    style.configure("Section.TLabel", background=c["bg"], foreground=c["text"],
                    font=font(12, "bold"))
    style.configure("SurfaceSection.TLabel", background=c["surface"], foreground=c["text"],
                    font=font(12, "bold"))

    # --- 按钮
    style.configure("TButton", background=c["surface"], foreground=c["text"],
                    bordercolor=c["border"], borderwidth=1, relief="solid",
                    padding=(14, 7), font=base, focuscolor=c["bg"])
    style.map("TButton",
              background=[("pressed", c["surface_alt"]), ("active", c["surface_alt"]),
                          ("disabled", c["disabled"])],
              foreground=[("disabled", c["faint"])],
              bordercolor=[("active", c["accent"])])

    style.configure("Accent.TButton", background=c["accent"], foreground="#FFFFFF",
                    bordercolor=c["accent"], padding=(16, 7), font=font(11, "bold"))
    style.map("Accent.TButton",
              background=[("pressed", c["accent_lo"]), ("active", c["accent_hi"]),
                          ("disabled", c["disabled"])],
              bordercolor=[("pressed", c["accent_lo"]), ("active", c["accent_hi"]),
                           ("disabled", c["disabled"])],
              foreground=[("disabled", c["faint"])])

    style.configure("Danger.TButton", background=c["danger"], foreground="#FFFFFF",
                    bordercolor=c["danger"], padding=(16, 7), font=font(11, "bold"))
    style.map("Danger.TButton",
              background=[("pressed", c["danger"]), ("active", c["danger"]),
                          ("disabled", c["disabled"])],
              foreground=[("disabled", c["faint"])])

    # 深色标题栏里的按钮
    style.configure("HeaderGhost.TButton", background=c["header"], foreground=c["header_text"],
                    bordercolor=c["header_sub"], padding=(13, 6), font=base)
    style.map("HeaderGhost.TButton",
              background=[("active", c["accent_lo"]), ("pressed", c["accent_lo"]),
                          ("disabled", c["header"])],
              bordercolor=[("active", c["accent_hi"])],
              foreground=[("disabled", c["header_sub"])])

    for name, bg in (("Link.TButton", c["bg"]), ("SurfaceLink.TButton", c["surface"])):
        style.configure(name, background=bg, foreground=c["accent"], bordercolor=bg,
                        lightcolor=bg, darkcolor=bg, borderwidth=0,
                        padding=(2, 2), font=font(10))
        style.map(name,
                  background=[("active", bg), ("pressed", bg)],
                  bordercolor=[("active", bg)],
                  foreground=[("active", c["accent_hi"]), ("disabled", c["faint"])])

    # --- 输入
    style.configure("TEntry", fieldbackground=c["surface"], foreground=c["text"],
                    bordercolor=c["border"], lightcolor=c["border"], darkcolor=c["border"],
                    borderwidth=1, relief="solid", padding=6, insertcolor=c["text"])
    style.map("TEntry",
              bordercolor=[("focus", c["accent"])],
              lightcolor=[("focus", c["accent"])],
              darkcolor=[("focus", c["accent"])],
              fieldbackground=[("disabled", c["disabled"])],
              foreground=[("disabled", c["faint"])])

    style.configure("TSpinbox", fieldbackground=c["surface"], foreground=c["text"],
                    background=c["surface"], bordercolor=c["border"], arrowcolor=c["muted"],
                    borderwidth=1, relief="solid", padding=5)
    style.map("TSpinbox",
              bordercolor=[("focus", c["accent"])],
              fieldbackground=[("disabled", c["disabled"])],
              foreground=[("disabled", c["faint"])],
              arrowcolor=[("disabled", c["faint"])])

    style.configure("TCombobox", fieldbackground=c["surface"], foreground=c["text"],
                    background=c["surface"], bordercolor=c["border"], arrowcolor=c["muted"],
                    borderwidth=1, relief="solid", padding=5)
    style.map("TCombobox",
              bordercolor=[("focus", c["accent"])],
              fieldbackground=[("readonly", c["surface"]), ("disabled", c["disabled"])])

    # --- 勾选 / 单选
    for kind in ("TCheckbutton", "TRadiobutton"):
        for prefix, bg in (("", c["bg"]), ("Surface.", c["surface"])):
            name = prefix + kind
            style.configure(name, background=bg, foreground=c["text"], font=base,
                            focuscolor=bg, padding=(0, 4),
                            indicatorbackground=c["surface"],
                            indicatorforeground="#FFFFFF",
                            indicatormargin=(0, 0, 8, 0),
                            bordercolor=c["border"], lightcolor=c["border"],
                            darkcolor=c["border"])
            style.map(name,
                      background=[("active", bg)],
                      foreground=[("disabled", c["faint"])],
                      indicatorbackground=[("selected", c["accent"]),
                                           ("disabled", c["disabled"]),
                                           ("active", c["surface_alt"])],
                      indicatorforeground=[("disabled", c["faint"])],
                      bordercolor=[("selected", c["accent"]), ("disabled", c["disabled"])],
                      lightcolor=[("selected", c["accent"])],
                      darkcolor=[("selected", c["accent"])])

    # --- 分组框
    style.configure("TLabelframe", background=c["surface"], bordercolor=c["border"],
                    borderwidth=1, relief="solid", padding=12)
    style.configure("TLabelframe.Label", background=c["surface"], foreground=c["accent"],
                    font=font(11, "bold"))

    # --- 表格
    style.configure("Treeview", background=c["surface"], fieldbackground=c["surface"],
                    foreground=c["text"], bordercolor=c["border"], borderwidth=0,
                    rowheight=32, font=base)
    style.configure("Treeview.Heading", background=c["surface_alt"], foreground=c["muted"],
                    font=font(10, "bold"), relief="flat", padding=(8, 8), borderwidth=0)
    style.map("Treeview.Heading", background=[("active", c["surface_alt"])])
    style.map("Treeview",
              background=[("selected", c["accent_soft"])],
              foreground=[("selected", c["text"])])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])   # 去掉外边框

    # --- 滚动条
    style.configure("Vertical.TScrollbar", background=c["border"], troughcolor=c["bg"],
                    bordercolor=c["bg"], arrowcolor=c["muted"], borderwidth=0, width=11)
    style.configure("Horizontal.TScrollbar", background=c["border"], troughcolor=c["bg"],
                    bordercolor=c["bg"], arrowcolor=c["muted"], borderwidth=0)
    for orient in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.map(orient, background=[("active", c["faint"]), ("pressed", c["muted"])])

    # --- 进度条
    style.configure("TProgressbar", background=c["accent"], troughcolor=c["surface_alt"],
                    bordercolor=c["surface_alt"], lightcolor=c["accent"], darkcolor=c["accent"],
                    borderwidth=0, thickness=6)

    # --- 分隔线 / 选项卡
    style.configure("TSeparator", background=c["border"])
    style.configure("TNotebook", background=c["bg"], bordercolor=c["border"], borderwidth=0,
                    tabmargins=(0, 4, 0, 0))
    style.configure("TNotebook.Tab", background=c["bg"], foreground=c["muted"],
                    padding=(18, 9), font=base, borderwidth=1,
                    bordercolor=c["border"], lightcolor=c["bg"], darkcolor=c["bg"])
    style.map("TNotebook.Tab",
              background=[("selected", c["surface"])],
              foreground=[("selected", c["accent"])],
              lightcolor=[("selected", c["surface"])],
              darkcolor=[("selected", c["surface"])],
              expand=[("selected", (0, 0, 0, 0))])


# ---------------------------------------------------------------- 小部件

class Badge(tk.Label):
    """一个带背景色的小标签，用来表示状态。"""

    TONES = {
        "success": ("success", "success_soft"),
        "warning": ("warning", "warning_soft"),
        "danger":  ("danger", "danger_soft"),
        "info":    ("info", "info_soft"),
        "accent":  ("accent", "accent_soft"),
        "muted":   ("muted", "surface_alt"),
    }

    def __init__(self, master, text="", tone="muted", **kw):
        fg, bg = self.TONES.get(tone, self.TONES["muted"])
        kw.setdefault("padx", 9)
        kw.setdefault("pady", 2)
        super().__init__(master, text=text, fg=C[fg], bg=C[bg],
                         font=font(10, "bold"), **kw)

    def set(self, text, tone="muted"):
        fg, bg = self.TONES.get(tone, self.TONES["muted"])
        self.config(text=text, fg=C[fg], bg=C[bg])


def card(master, **kw):
    """一张带细边框的白色卡片。"""
    kw.setdefault("bg", C["surface"])
    kw.setdefault("highlightbackground", C["border"])
    kw.setdefault("highlightcolor", C["border"])
    kw.setdefault("highlightthickness", 1)
    kw.setdefault("bd", 0)
    return tk.Frame(master, **kw)


def bind_mousewheel(widget, canvas):
    """把滚轮绑定到指定 canvas，只在鼠标位于该控件内时生效（避免全局 bind_all 串台）。"""
    def _on_wheel(event):
        if not canvas.winfo_exists():
            return
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            # Windows 是 120 的倍数，macOS 是较小的整数
            delta = -1 if event.delta > 0 else 1
            if abs(event.delta) >= 120:
                delta = int(-event.delta / 120)
        try:
            canvas.yview_scroll(delta, "units")
        except tk.TclError:
            pass

    def _enter(_):
        widget.bind_all("<MouseWheel>", _on_wheel)
        widget.bind_all("<Button-4>", _on_wheel)
        widget.bind_all("<Button-5>", _on_wheel)

    def _leave(_):
        widget.unbind_all("<MouseWheel>")
        widget.unbind_all("<Button-4>")
        widget.unbind_all("<Button-5>")

    widget.bind("<Enter>", _enter, add="+")
    widget.bind("<Leave>", _leave, add="+")
    widget.bind("<Destroy>", _leave, add="+")


def scrollable(master):
    """构造一个纵向可滚动区域，返回 (外层 frame, 内容 frame)。"""
    outer = ttk.Frame(master)
    canvas = tk.Canvas(outer, bg=C["bg"], highlightthickness=0, bd=0)
    bar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)

    bar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    inner = ttk.Frame(canvas)
    window = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _sync_scrollregion(_=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _sync_width(event):
        canvas.itemconfig(window, width=event.width)

    inner.bind("<Configure>", _sync_scrollregion)
    canvas.bind("<Configure>", _sync_width)
    bind_mousewheel(outer, canvas)
    return outer, inner


def center(window, width=None, height=None):
    """把窗口摆到屏幕中央（可顺带设定尺寸）。"""
    window.update_idletasks()
    width = width or window.winfo_width()
    height = height or window.winfo_height()
    x = max(0, (window.winfo_screenwidth() - width) // 2)
    y = max(0, (window.winfo_screenheight() - height) // 3)
    window.geometry("%dx%d+%d+%d" % (width, height, x, y))


def apply_icon(window):
    """尽力设置窗口图标，失败静默忽略。"""
    from Scripts.Utils import resource_path
    try:
        if platform.system() == "Windows":
            ico = resource_path(os.path.join("UI", "Image", "favicon.ico"))
            if os.path.exists(ico):
                window.iconbitmap(ico)
        else:
            png = resource_path(os.path.join("UI", "Image", "TsinghuaYKT.jpg"))
            if os.path.exists(png):
                from PIL import Image, ImageTk
                img = Image.open(png).resize((64, 64))
                photo = ImageTk.PhotoImage(img)
                window.iconphoto(False, photo)
                window._icon_ref = photo      # 防止被回收
    except Exception:
        pass
