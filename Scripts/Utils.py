# -*- coding: utf-8 -*-
"""配置读写、网络会话与若干通用工具。"""
import copy
import json
import os
import platform
import random
import sys
import tempfile
import threading

import requests
import urllib3

lock = threading.Lock()

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:97.0) "
              "Gecko/20100101 Firefox/97.0")
NO_PROXY = {"http": None, "https": None}
API_BASE = "https://pro.yuketang.cn"

# 复用连接，顺带给瞬时网络抖动一点重试机会
_session = requests.Session()
_session.trust_env = False          # 忽略系统代理，行为与原来的 proxies=None 一致
_adapter = requests.adapters.HTTPAdapter(
    max_retries=urllib3.util.retry.Retry(
        total=2, backoff_factor=0.5,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"])),
    pool_connections=8, pool_maxsize=16)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

DEFAULT_TIMEOUT = 15


def auth_headers(sessionid):
    """构造带 sessionid 的请求头。"""
    return {"Cookie": "sessionid=%s" % sessionid, "User-Agent": USER_AGENT}


def http_get(url, headers=None, timeout=DEFAULT_TIMEOUT, **kw):
    return _session.get(url, headers=headers, timeout=timeout, proxies=NO_PROXY, **kw)


def http_post(url, headers=None, data=None, timeout=DEFAULT_TIMEOUT, **kw):
    return _session.post(url, headers=headers, data=data, timeout=timeout,
                         proxies=NO_PROXY, **kw)


def dict_result(text):
    """json 字符串转 dict。"""
    return dict(json.loads(text))


def test_network():
    """网络状态测试。"""
    for url in ("https://pro.yuketang.cn/favicon.ico", "https://www.baidu.com"):
        try:
            _session.get(url, timeout=5, proxies=NO_PROXY)
            return True
        except Exception:
            continue
    return False


def calculate_waittime(limit, type, custom_time):
    """计算答题等待时间。

    type 1 = 随机，2 = 自定义。
    """
    def default_calculate(limit):
        if limit == -1:
            return random.randint(5, 20)
        if limit > 15:
            return random.randint(5, limit - 10)
        return 0

    if type == 2:
        # 自定义时间超过剩余时间就退回随机算法，避免超时
        if limit != -1 and custom_time > limit:
            return default_calculate(limit)
        return max(0, int(custom_time))
    return default_calculate(limit)


# ---------------------------------------------------------------- 配置

def get_initial_data():
    """默认配置信息。"""
    return {
        "sessionid": "",
        "ui_theme": "auto",                 # auto / light / dark
        "auto_danmu": True,
        "danmu_config": {
            "danmu_limit": 5,
        },
        "auto_answer": True,
        "answer_config": {
            "answer_delay": {
                "type": 1,
                "custom": {"time": 0},
            },
            "auto_ai": False,               # 收到新题目时自动调用 AI 作答
        },
        "ai_config": {
            "provider": "glm",
            "api_key": "",
            "base_url": "https://sec.llm.autos",
            "model": "glm-5.3-flash",
            "enable_thinking": True,
            "concurrency": 3,               # 批量解题的并发数
        },
    }


def merge_defaults(config, defaults=None):
    """把缺失的默认键补进配置，老版本配置文件也能平滑升级。"""
    if defaults is None:
        defaults = get_initial_data()
    merged = copy.deepcopy(defaults)
    for key, value in (config or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_defaults(value, merged[key])
        else:
            merged[key] = value
    return merged


def load_config():
    """读取配置文件；文件损坏或缺失时回落到默认配置。"""
    path = get_config_path()
    data = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # 配置损坏时备份一份再用默认值，避免用户数据被静默覆盖
            try:
                os.replace(path, path + ".bak")
            except OSError:
                pass
            data = {}
    config = merge_defaults(data)
    if config != data:
        save_config(config)
    return config


def save_config(config):
    """原子写入配置，避免写一半掉电导致配置损坏。"""
    path = get_config_path()
    directory = os.path.dirname(path)
    with lock:
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise


def get_config_path():
    """配置文件路径。"""
    return os.path.join(get_config_dir(), "config.json")


def get_config_dir():
    """配置文件所在文件夹（按平台放到各自的用户数据目录）。"""
    system = platform.system()
    if system == "Windows":
        home = os.environ.get("APPDATA") or os.environ.get("USERPROFILE") or os.path.expanduser("~")
        route = os.path.join(home, "RainClassroomAssistant")
    elif system == "Darwin":
        route = os.path.join(os.path.expanduser("~"), "Library", "RainClassroomAssistant")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        route = os.path.join(base, "RainClassroomAssistant")
    os.makedirs(route, exist_ok=True)
    return route


def get_output_dir():
    """题目截图的存放目录，跟随配置目录，不受启动时工作目录影响。"""
    route = os.path.join(get_config_dir(), "output")
    os.makedirs(route, exist_ok=True)
    return route


# ---------------------------------------------------------------- 雨课堂接口

def get_user_info(sessionid):
    """获取用户信息。"""
    r = http_get(API_BASE + "/api/v3/user/basic-info", headers=auth_headers(sessionid))
    rtn = dict_result(r.text)
    if rtn.get("code") != 0 or not rtn.get("data"):
        raise Exception("获取用户信息失败：%s" % rtn.get("msg", rtn.get("code")))
    return rtn["code"], rtn["data"]


def get_on_lesson(sessionid):
    """获取用户当前正在上课列表。"""
    r = http_get(API_BASE + "/api/v3/classroom/on-lesson", headers=auth_headers(sessionid))
    rtn = dict_result(r.text)
    data = rtn.get("data") or {}
    if rtn.get("code") not in (0, None) and not data:
        raise Exception("获取课程列表失败：%s" % rtn.get("msg", rtn.get("code")))
    return data.get("onLessonClassrooms", [])


def get_on_lesson_old(sessionid):
    """获取用户当前正在上课的列表（旧版接口）。"""
    r = http_get(API_BASE + "/v/course_meta/on_lesson_courses", headers=auth_headers(sessionid))
    return dict_result(r.text)["on_lessons"]


def resource_path(relative_path):
    """解决打包成 exe 后的资源路径问题。"""
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)
