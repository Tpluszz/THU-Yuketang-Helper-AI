# -*- coding: utf-8 -*-
"""JS ⇄ Python 桥：pywebview 把这个对象的公开方法暴露为 window.pywebview.api.*

约定：
- 以下划线开头的属性不会暴露给 JS（pywebview 的规则），内部状态都这样命名。
- 所有接口都不抛异常，出错统一返回 {"ok": False, "error": "..."}，界面直接展示。
- Python → JS 的事件经一个发送线程排队发出：监听线程、websocket 线程不会被界面卡住，
  事件顺序也有保证。
"""
import functools
import json
import os
import platform
import queue
import subprocess
import threading
import traceback
import webbrowser

from Scripts.App import App


def _safe(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            traceback.print_exc()
            return {"ok": False, "error": str(exc) or exc.__class__.__name__}
    return wrapper


def reveal(path):
    """在访达 / 资源管理器里定位文件。"""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", "-R", path])
        elif system == "Windows":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])
    except OSError:
        pass


def open_path(path):
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", path])
        elif system == "Windows":
            os.startfile(path)                  # noqa: 仅 Windows 有
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass


class Bridge:
    def __init__(self, app=None):
        self._window = None
        self._ready = False
        self._queue = queue.Queue()
        self._app = app or App(emit=self._emit, raise_window=self._raise)
        threading.Thread(target=self._sender, daemon=True).start()

    # ------------------------------------------------------------ 内部

    def _attach(self, window):
        self._window = window

    def _emit(self, event, data):
        self._queue.put((event, data))

    def _sender(self):
        while True:
            event, data = self._queue.get()
            if event is None:
                return
            if not (self._window and self._ready):
                continue            # 页面还没就绪：初始状态由 ready() 一次性给全
            try:
                payload = json.dumps({"event": event, "data": data})   # ASCII 转义，JS 里安全
                self._window.evaluate_js("window.__onEvent && window.__onEvent(%s)" % payload)
            except Exception:
                pass

    def _raise(self):
        win = self._window
        if not win:
            return
        try:
            win.restore()
            win.show()
            win.on_top = True
            threading.Timer(1.5, lambda: setattr(win, "on_top", False)).start()
        except Exception:
            pass

    def _shutdown(self):
        self._ready = False
        self._app.shutdown()
        self._queue.put((None, None))

    # ------------------------------------------------------------ 启动

    @_safe
    def ready(self):
        """页面加载完成后调用：返回全部初始状态，然后开始检查登录。"""
        self._ready = True
        boot = self._app.bootstrap()
        threading.Thread(target=self._app.start, daemon=True).start()
        return boot

    @_safe
    def state(self):
        return self._app.state()

    @_safe
    def lessons(self):
        return self._app.lessons_payload()

    # ------------------------------------------------------------ 登录

    @_safe
    def login_start(self):
        return self._app.login_start()

    @_safe
    def login_refresh(self):
        return self._app.login_refresh()

    @_safe
    def login_cancel(self):
        return self._app.login_cancel()

    @_safe
    def logout(self):
        return self._app.logout()

    @_safe
    def recheck_login(self):
        self._app.refresh_login()
        return {"ok": True}

    # ------------------------------------------------------------ 监听 / 测试

    @_safe
    def start_monitor(self):
        return self._app.start_monitor()

    @_safe
    def stop_monitor(self):
        return self._app.stop_monitor()

    @_safe
    def enter_test_mode(self):
        return self._app.enter_test_mode()

    @_safe
    def exit_test_mode(self):
        return self._app.exit_test_mode()

    # ------------------------------------------------------------ 题目

    @_safe
    def lesson_detail(self, lesson_id):
        return dict(self._app.lesson_detail(lesson_id), ok=True)

    @_safe
    def problem_image(self, lesson_id, problem_id, width=480):
        return {"ok": True, "image": self._app.problem_image(lesson_id, problem_id, width)}

    @_safe
    def save_answer(self, lesson_id, problem_id, answers):
        return self._app.save_answer(lesson_id, problem_id, answers)

    @_safe
    def submit_answer(self, lesson_id, problem_id, answers):
        return self._app.submit_answer(lesson_id, problem_id, answers)

    @_safe
    def ai_solve(self, lesson_id, problem_id):
        return self._app.ai_solve(lesson_id, problem_id)

    @_safe
    def ai_explain(self, lesson_id, problem_id):
        return self._app.ai_explain(lesson_id, problem_id)

    @_safe
    def ai_review(self, lesson_id, problem_id, answers):
        return self._app.ai_review(lesson_id, problem_id, answers)

    @_safe
    def solve_all(self, lesson_id):
        return self._app.solve_all(lesson_id)

    @_safe
    def cancel_solve_all(self, lesson_id):
        return self._app.cancel_solve_all(lesson_id)

    @_safe
    def confirm_decide(self, token, ok, answers=None):
        return self._app.confirm_decide(token, ok, answers)

    # ------------------------------------------------------------ 历史 / 导出

    @_safe
    def list_history(self):
        return {"ok": True, "items": self._app.list_history()}

    @_safe
    def delete_history(self, record_id):
        return self._app.delete_history(record_id)

    @_safe
    def export_pdf(self, lesson_id):
        import webview
        info = self._app.export_info(lesson_id)
        if not info["pages"]:
            return {"ok": False, "error": "这节课还没有下载到课件截图"}
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=downloads if os.path.isdir(downloads) else os.path.expanduser("~"),
            save_filename=info["name"], file_types=("PDF 文件 (*.pdf)",))
        if not result:
            return {"ok": False, "cancelled": True}
        path = result if isinstance(result, str) else result[0]
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        return self._app.export_lesson_pdf(lesson_id, path)

    @_safe
    def reveal(self, path):
        reveal(path)
        return {"ok": True}

    # ------------------------------------------------------------ 设置

    @_safe
    def get_settings(self):
        return {"ok": True, "settings": self._app.get_settings()}

    @_safe
    def save_settings(self, settings):
        return self._app.save_settings(settings)

    @_safe
    def set_onboarded(self, extra=None):
        return self._app.set_onboarded(extra)

    @_safe
    def test_ai(self, ai_config):
        return self._app.test_ai(ai_config)

    @_safe
    def list_models(self, ai_config):
        return self._app.list_models(ai_config)

    @_safe
    def test_notify(self, notify_config):
        return self._app.test_notify(notify_config)

    @_safe
    def open_config_dir(self):
        open_path(self._app.meta()["configDir"])
        return {"ok": True}

    @_safe
    def open_url(self, url):
        if str(url).startswith(("https://", "http://")):
            webbrowser.open(url)
        return {"ok": True}
