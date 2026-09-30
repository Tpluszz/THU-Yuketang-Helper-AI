# -*- coding: utf-8 -*-
"""课堂存档：每节课的题目、答案、提交结果、AI 讲解都落到本地，下课后还能回看。

一节课一个 JSON 文件，放在配置目录的 history/ 下。
"""
import datetime
import json
import os
import re
import threading

from Scripts.Utils import get_config_dir

# 只存这些字段：雨课堂返回的题目对象字段很多且会变，全存既臃肿又不稳定
PROBLEM_FIELDS = ("problemId", "problemType", "body", "options", "blanks", "page",
                  "image", "answers", "result", "explanation", "review")

SAVE_DELAY = 2.0     # 连续更新时合并写盘


def history_dir():
    path = os.path.join(get_config_dir(), "history")
    os.makedirs(path, exist_ok=True)
    return path


def _safe_name(text):
    return re.sub(r"[^0-9A-Za-z_.-]", "_", str(text))[:80] or "lesson"


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else None


def record_from_lesson(lesson):
    """把一个进行中的 Lesson 转成可存盘的记录。"""
    problems = []
    for p in lesson.snapshot_problems():
        problems.append({k: p.get(k) for k in PROBLEM_FIELDS if k in p})
    return {
        "id": _safe_name(lesson.lessonid),
        "lessonId": str(lesson.lessonid),
        "lessonName": lesson.lessonname,
        "classroomId": str(getattr(lesson, "classroomid", "") or ""),
        "startedAt": _iso(getattr(lesson, "started_at", None)),
        "endedAt": _iso(getattr(lesson, "ended_at", None)),
        "finished": bool(getattr(lesson, "finished", False)),
        "presentations": list(getattr(lesson, "presentations", []) or []),
        "problems": problems,
    }


def summarize(record):
    problems = record.get("problems") or []
    return {
        "id": record.get("id"),
        "lessonName": record.get("lessonName") or "未命名课程",
        "startedAt": record.get("startedAt"),
        "endedAt": record.get("endedAt"),
        "finished": record.get("finished", False),
        "problemCount": len(problems),
        "answered": sum(1 for p in problems if p.get("result") is not None),
        "slides": len(record.get("presentations") or []),
    }


class HistoryStore:
    def __init__(self, directory=None):
        self.dir = directory or history_dir()
        os.makedirs(self.dir, exist_ok=True)
        self._lock = threading.Lock()
        self._timers = {}

    def path(self, record_id):
        return os.path.join(self.dir, _safe_name(record_id) + ".json")

    # ------------------------------------------------------------ 写

    def save_record(self, record):
        path = self.path(record["id"])
        tmp = path + ".tmp"
        with self._lock:
            # 已有文件时保留最早的开始时间（程序中途重启也不会改掉）
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        old = json.load(f)
                    record["startedAt"] = old.get("startedAt") or record.get("startedAt")
                    # 讲解/复核是回看时加上去的，别被课上的新快照覆盖掉
                    extra = {str(p.get("problemId")): p for p in old.get("problems", [])}
                    for p in record.get("problems", []):
                        o = extra.get(str(p.get("problemId")))
                        if o:
                            for key in ("explanation", "review"):
                                if o.get(key) and not p.get(key):
                                    p[key] = o[key]
                except (OSError, ValueError):
                    pass
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        return path

    def save_lesson(self, lesson):
        if getattr(lesson, "archive", True) is False:
            return None
        return self.save_record(record_from_lesson(lesson))

    def schedule_save(self, lesson):
        """合并短时间内的多次更新，避免推题高峰时频繁写盘。"""
        if getattr(lesson, "archive", True) is False:
            return
        key = str(lesson.lessonid)
        with self._lock:
            old = self._timers.pop(key, None)
            if old:
                old.cancel()
            timer = threading.Timer(SAVE_DELAY, self._fire, args=(key, lesson))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _fire(self, key, lesson):
        with self._lock:
            self._timers.pop(key, None)
        try:
            self.save_lesson(lesson)
        except Exception:
            pass

    def flush(self, lesson):
        """立即写盘（下课、退出时用）。"""
        key = str(lesson.lessonid)
        with self._lock:
            timer = self._timers.pop(key, None)
        if timer:
            timer.cancel()
        return self.save_lesson(lesson)

    def delete(self, record_id):
        path = self.path(record_id)
        if os.path.exists(path):
            os.remove(path)

    # ------------------------------------------------------------ 读

    def load(self, record_id):
        with open(self.path(record_id), "r", encoding="utf-8") as f:
            return json.load(f)

    def list(self):
        items = []
        for name in os.listdir(self.dir):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.dir, name), "r", encoding="utf-8") as f:
                    items.append(summarize(json.load(f)))
            except (OSError, ValueError):
                continue
        items.sort(key=lambda x: x.get("startedAt") or "", reverse=True)
        return items


class HistoryLesson:
    """把一条存档包装成和 Lesson 接口一致的对象，界面可以直接复用。

    只读：不能提交到雨课堂；但可以让 AI 解答/讲解，结果写回存档。
    """
    readonly = True
    archive = False
    finished = True

    def __init__(self, record, store, config):
        self.record = record
        self.store = store
        self.config = config
        self.lessonid = "h:" + record["id"]
        self.lessonname = record.get("lessonName") or "未命名课程"
        self.classroomid = record.get("classroomId")
        self.presentations = record.get("presentations") or []
        self.problems_ls = record.setdefault("problems", [])
        self._lock = threading.RLock()

    def snapshot_problems(self):
        with self._lock:
            return list(self.problems_ls)

    def find_problem(self, problemid):
        with self._lock:
            for p in self.problems_ls:
                if str(p.get("problemId")) == str(problemid):
                    return p
        return None

    @property
    def problem_count(self):
        return len(self.problems_ls)

    @property
    def answered_count(self):
        return sum(1 for p in self.problems_ls if p.get("result") is not None)

    def notify_update(self):
        self.store.save_record(self.record)

    def submit_problem(self, problem):
        raise Exception("这是历史记录，课已经结束，不能再提交")

    def stop(self):
        pass
