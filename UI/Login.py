# -*- coding: utf-8 -*-
"""登录对话框：微信扫码获取 sessionid。"""
import json
import threading
import time
import tkinter as tk
from io import BytesIO
from tkinter import ttk

import requests
import websocket
from PIL import Image, ImageTk

from Scripts.Utils import USER_AGENT, dict_result, http_get, http_post, save_config
from UI import Theme

LOGIN_WSS_URL = "wss://pro.yuketang.cn/wsapp/"
WEB_LOGIN_URL = "https://pro.yuketang.cn/pc/web_login"
QRCODE_TTL = 60          # 二维码有效期（秒）
QRCODE_SIZE = 240


class LoginDialog:
    def __init__(self, parent, main_window):
        self.parent = parent
        self.main_window = main_window
        self.config = main_window.config

        self.flush_on = True
        self.sessionid = ""
        self.login_success = False
        self._closed = False
        self.wsapp = None
        self._qr_photo = None
        self._countdown = QRCODE_TTL

        self.top = tk.Toplevel(parent)
        self.top.title("扫码登录")
        self.top.configure(bg=Theme.C["bg"])
        self.top.resizable(False, False)
        Theme.apply_icon(self.top)

        self.create_ui()
        Theme.center(self.top, 380, 500)

        self.top.protocol("WM_DELETE_WINDOW", self.close_window)
        self.top.bind("<Escape>", lambda _: self.close_window())
        self.top.transient(parent)
        self.top.grab_set()

        self.start_wssapp()
        self._tick()

    # ------------------------------------------------------------ 界面

    def create_ui(self):
        c = Theme.C
        root = ttk.Frame(self.top)
        root.pack(fill=tk.BOTH, expand=True, padx=24, pady=22)

        ttk.Label(root, text="微信扫码登录雨课堂",
                  font=Theme.font(15, "bold")).pack()
        ttk.Label(root, text="扫码仅用于获取登录状态，账号信息不会上传到任何第三方。",
                  style="Muted.TLabel", wraplength=300,
                  justify=tk.CENTER).pack(pady=(6, 16))

        frame = Theme.card(root, width=QRCODE_SIZE + 16, height=QRCODE_SIZE + 16)
        frame.pack()
        frame.pack_propagate(False)
        self.qrcode_label = tk.Label(frame, bg=c["surface"], fg=c["faint"],
                                     font=Theme.font(11), text="正在获取二维码……")
        self.qrcode_label.pack(fill=tk.BOTH, expand=True)

        self.status_label = ttk.Label(root, text="", style="Muted.TLabel",
                                      wraplength=300, justify=tk.CENTER)
        self.status_label.pack(pady=(14, 4))

        self.refresh_btn = ttk.Button(root, text="刷新二维码", command=self.request_qrcode, width=12)
        self.refresh_btn.pack(pady=(6, 0))

    def set_status(self, text, tone="muted"):
        colors = {"muted": Theme.C["muted"], "success": Theme.C["success"],
                  "error": Theme.C["danger"], "warning": Theme.C["warning"]}
        self._ui(lambda: self.status_label.config(text=text,
                                                  foreground=colors.get(tone, Theme.C["muted"])))

    # ------------------------------------------------------------ websocket

    def start_wssapp(self):
        self.wsapp = websocket.WebSocketApp(
            url=LOGIN_WSS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close)
        threading.Thread(target=self.wsapp.run_forever, daemon=True).start()

    def _on_open(self, wsapp):
        self._request(wsapp)

    @staticmethod
    def _request(wsapp):
        wsapp.send(json.dumps({"op": "requestlogin", "role": "web",
                               "version": 1.4, "type": "qrcode", "from": "web"}))

    def request_qrcode(self):
        """手动或定时刷新二维码。"""
        self._countdown = QRCODE_TTL
        try:
            self._request(self.wsapp)
            self.set_status("二维码已刷新，请用微信扫码")
        except Exception:
            self.set_status("连接已断开，正在重新连接……", "warning")
            self.start_wssapp()

    def _on_error(self, wsapp, error):
        if self.flush_on:
            self.set_status("连接出错：%s" % error, "error")

    def _on_close(self, wsapp, close_status_code=None, close_msg=None):
        # websocket-client 会以 3 个参数调用该回调
        if self.flush_on and not self.login_success:
            self.set_status("连接已关闭，可点击「刷新二维码」重试", "warning")

    def _on_message(self, wsapp, message):
        try:
            data = dict_result(message)
        except Exception:
            return
        op = data.get("op")
        try:
            if op == "requestlogin":
                self._show_qrcode(data.get("ticket"))
            elif op == "scanqr":
                self.set_status("已扫码，请在手机上点击确认", "success")
            elif op == "loginsuccess":
                self._finish_login(data)
            elif op == "loginerror":
                self.set_status("登录失败，请刷新二维码后重试", "error")
        except Exception as exc:
            self.set_status("登录过程出错：%s" % exc, "error")

    def _show_qrcode(self, ticket):
        if not ticket:
            self.set_status("服务器未返回二维码，请稍后重试", "error")
            return
        try:
            content = http_get(ticket, headers={"User-Agent": USER_AGENT}, timeout=15).content
            image = Image.open(BytesIO(content)).resize((QRCODE_SIZE, QRCODE_SIZE), Image.LANCZOS)
        except Exception as exc:
            self.set_status("二维码下载失败：%s" % exc, "error")
            return
        # 图片必须在主线程里交给 tkinter
        self._ui(lambda: self._set_qr_image(image))
        self._countdown = QRCODE_TTL
        self.set_status("请使用微信扫描上方二维码")

    def _set_qr_image(self, image):
        self._qr_photo = ImageTk.PhotoImage(image)
        self.qrcode_label.config(image=self._qr_photo, text="")

    def _finish_login(self, data):
        payload = json.dumps({"UserID": data["UserID"], "Auth": data["Auth"]})
        r = http_post(WEB_LOGIN_URL, data=payload, headers={"User-Agent": USER_AGENT})
        cookies = dict(r.cookies)
        if "sessionid" not in cookies:
            self.set_status("登录接口未返回 sessionid，请重试", "error")
            return
        self.sessionid = cookies["sessionid"]
        self.config["sessionid"] = self.sessionid
        save_config(self.config)
        self.login_success = True
        self.set_status("登录成功", "success")
        self._ui(self.close_window)

    # ------------------------------------------------------------ 定时器

    def _tick(self):
        """每秒跑一次的倒计时，到点自动刷新二维码。"""
        if not self.flush_on or not self._alive():
            return
        self._countdown -= 1
        if self._countdown <= 0 and not self.login_success:
            self.request_qrcode()
        self.top.after(1000, self._tick)

    # ------------------------------------------------------------ 杂项

    def _alive(self):
        if self._closed:
            return False
        try:
            return bool(self.top.winfo_exists())
        except (tk.TclError, RuntimeError):
            return False

    def _ui(self, func):
        """把回调丢回主线程；websocket 线程里不能直接碰 Tcl 接口。"""
        if self._closed:
            return
        try:
            self.top.after(0, func)
        except (tk.TclError, RuntimeError):
            pass

    def save(self, sessionid):
        """保留旧接口：保存 sessionid。"""
        self.config["sessionid"] = sessionid
        save_config(self.config)

    def close_window(self):
        self._closed = True
        self.flush_on = False
        if self.wsapp:
            try:
                self.wsapp.close()
            except Exception:
                pass
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        try:
            self.top.destroy()
        except tk.TclError:
            pass
