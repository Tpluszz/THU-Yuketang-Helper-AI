# -*- coding: utf-8 -*-
"""扫码登录流程，与界面无关。

通过 on_event(dict) 回调把进度交给界面：
  {"type": "qr", "image": "data:image/png;base64,..."}   新二维码
  {"type": "status", "text": "...", "tone": "muted|success|warning|error"}
  {"type": "done", "sessionid": "..."}                    登录成功
"""
import base64
import json
import threading
import time

import websocket

from Scripts.Utils import USER_AGENT, dict_result, http_get, http_post

LOGIN_WSS_URL = "wss://pro.yuketang.cn/wsapp/"
WEB_LOGIN_URL = "https://pro.yuketang.cn/pc/web_login"
QRCODE_TTL = 60          # 二维码有效期（秒），到点自动换一张


class LoginFlow:
    def __init__(self, on_event):
        self.on_event = on_event
        self.wsapp = None
        self.active = False
        self.done = False
        self._countdown = QRCODE_TTL

    def _emit(self, **event):
        try:
            self.on_event(event)
        except Exception:
            pass

    def status(self, text, tone="muted"):
        self._emit(type="status", text=text, tone=tone)

    # ------------------------------------------------------------ 生命周期

    def start(self):
        self.active = True
        self.done = False
        self._connect()
        threading.Thread(target=self._ticker, daemon=True).start()

    def cancel(self):
        self.active = False
        if self.wsapp:
            try:
                self.wsapp.close()
            except Exception:
                pass

    def refresh(self):
        """手动或定时换一张二维码。"""
        self._countdown = QRCODE_TTL
        try:
            self._request(self.wsapp)
            self.status("二维码已刷新，请用微信扫码")
        except Exception:
            self.status("连接已断开，正在重新连接……", "warning")
            self._connect()

    def _ticker(self):
        while self.active and not self.done:
            time.sleep(1)
            self._countdown -= 1
            if self._countdown <= 0:
                self.refresh()

    # ------------------------------------------------------------ websocket

    def _connect(self):
        self.wsapp = websocket.WebSocketApp(
            url=LOGIN_WSS_URL,
            on_open=lambda ws: self._request(ws),
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close)
        threading.Thread(target=self.wsapp.run_forever, daemon=True).start()

    @staticmethod
    def _request(wsapp):
        wsapp.send(json.dumps({"op": "requestlogin", "role": "web",
                               "version": 1.4, "type": "qrcode", "from": "web"}))

    def _on_error(self, wsapp, error):
        if self.active and not self.done:
            self.status("连接出错：%s" % error, "error")

    def _on_close(self, wsapp, code=None, msg=None):
        if self.active and not self.done:
            self.status("连接已关闭，可点「刷新二维码」重试", "warning")

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
                self.status("已扫码，请在手机上点「确认登录」", "success")
            elif op == "loginsuccess":
                self._finish(data)
            elif op == "loginerror":
                self.status("登录失败，请刷新二维码后重试", "error")
        except Exception as exc:
            self.status("登录过程出错：%s" % exc, "error")

    def _show_qrcode(self, ticket):
        if not ticket:
            self.status("服务器没有返回二维码，请稍后重试", "error")
            return
        try:
            r = http_get(ticket, headers={"User-Agent": USER_AGENT}, timeout=15)
            mime = r.headers.get("Content-Type", "image/png").split(";")[0] or "image/png"
            data = base64.b64encode(r.content).decode()
        except Exception as exc:
            self.status("二维码下载失败：%s" % exc, "error")
            return
        self._countdown = QRCODE_TTL
        self._emit(type="qr", image="data:%s;base64,%s" % (mime, data))
        self.status("请用微信扫描二维码")

    def _finish(self, data):
        payload = json.dumps({"UserID": data["UserID"], "Auth": data["Auth"]})
        r = http_post(WEB_LOGIN_URL, data=payload, headers={"User-Agent": USER_AGENT})
        sessionid = dict(r.cookies).get("sessionid")
        if not sessionid:
            self.status("登录接口没有返回 sessionid，请重试", "error")
            return
        self.done = True
        self.status("登录成功", "success")
        self._emit(type="done", sessionid=sessionid)
        self.cancel()
