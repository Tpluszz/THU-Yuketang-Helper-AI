# -*- coding: utf-8 -*-
"""待学习：把散在各门课里的未完成内容集中列出来。

只做「找出来 + 给出官方页面地址」，不碰任何上报进度的接口
（/video-log/heartbeat/、翻页已读之类）——那属于伪造学习记录。
"""
import concurrent.futures

from Scripts.Utils import API_BASE, auth_headers, http_get

WEB_BASE = "https://pro.yuketang.cn/v2/web"

# 学习日志里的活动类型
T_COURSEWARE = 2      # 课件（翻页阅读，view.done 标记是否读完）
T_LESSON = 14         # 授课（课堂回放）
T_CHAPTER = 15        # 自学章节（MOOC，含视频/图文 leaf）
T_QUIZ = 20           # 测验

TYPE_NAME = {T_COURSEWARE: "课件", T_LESSON: "授课", T_CHAPTER: "自学章节", T_QUIZ: "测验"}

FETCH_WORKERS = 6
TIMEOUT = 20


def _headers(sessionid):
    h = dict(auth_headers(sessionid))
    h["xtbz"] = "ykt"          # 学堂在线系列接口的业务标识，缺了部分接口返回空
    return h


def list_courses(sessionid):
    """当前账号的全部班级。"""
    r = http_get(API_BASE + "/v2/api/web/courses/list?identity=2",
                 headers=_headers(sessionid), timeout=TIMEOUT)
    data = (r.json().get("data") or {}).get("list") or []
    out = []
    for c in data:
        course = c.get("course") or {}
        out.append({
            "classroomId": c.get("classroom_id"),
            "courseId": course.get("id"),
            "name": course.get("name") or c.get("name") or "未命名课程",
            "teacher": (c.get("teacher") or {}).get("name") or "",
            "term": c.get("name") or "",
        })
    return out


def _activities(sessionid, classroom_id, limit=200):
    r = http_get(API_BASE + "/v2/api/web/logs/learn/%s?actype=-1&page=0&offset=%d"
                 % (classroom_id, limit), headers=_headers(sessionid), timeout=TIMEOUT)
    return (r.json().get("data") or {}).get("activities") or []


def courseware_url(course, item):
    """课件的官方阅读页。activity_id 就是学习日志里那条记录的 id。"""
    return ("%s/studentCards/%s/%s/%s/ppt?cid=%s&university_id=2598&platform_id=3&classroom_id=%s"
            % (WEB_BASE, course["classroomId"], item["coursewareId"],
               item["activityId"], course["courseId"], course["classroomId"]))


def course_url(course):
    """课程主页（学习日志）。"""
    return "%s/studentLog/%s?classroom_id=%s" % (WEB_BASE, course["classroomId"],
                                                 course["classroomId"])


def video_url(classroom_id, leaf_id):
    """MOOC 视频 leaf 的播放页。"""
    return "%s/video-student/%s/%s" % (WEB_BASE, classroom_id, leaf_id)


def scan_course(sessionid, course):
    """扫一门课，返回未完成的条目。"""
    items = []
    try:
        acts = _activities(sessionid, course["classroomId"])
    except Exception as exc:
        return {"course": course, "items": [], "error": str(exc)}

    for a in acts:
        t = a.get("type")
        if t == T_COURSEWARE:
            view = a.get("view") or {}
            total = a.get("count") or 0
            read = view.get("depth") or 0
            if view.get("done"):
                continue
            item = {
                "kind": "courseware",
                "typeName": "课件",
                "title": a.get("title") or "未命名课件",
                "coursewareId": str(a.get("courseware_id") or ""),
                "activityId": a.get("id"),
                "read": read, "total": total,
                "progress": ("%d / %d 页" % (read, total)) if total else "未读",
                "deadline": a.get("end"),
            }
            item["url"] = courseware_url(course, item)
            items.append(item)
        elif t == T_CHAPTER:
            # 自学章节只有整体计数，具体哪个 leaf 没学要点进去看
            content = a.get("content") or {}
            done, total = content.get("p_l"), content.get("l_n")
            if done is None or not total or done >= total:
                continue
            items.append({
                "kind": "chapter",
                "typeName": "自学章节",
                "title": a.get("title") or "自学内容",
                "coursewareId": str(a.get("courseware_id") or ""),
                "activityId": a.get("id"),
                "read": done, "total": total,
                "progress": "%d / %d 个单元" % (done, total),
                "deadline": None,
                "url": course_url(course),
            })
    return {"course": course, "items": items, "error": None}


def scan_all(sessionid, on_progress=None):
    """并发扫描所有课程。返回 {courses, items, errors}。"""
    courses = list_courses(sessionid)
    results = []
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futures = {pool.submit(scan_course, sessionid, c): c for c in courses}
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
            done += 1
            if on_progress:
                on_progress(done, len(courses))

    groups, errors = [], []
    for res in results:
        if res["error"]:
            errors.append({"course": res["course"]["name"], "error": res["error"]})
        if not res["items"]:
            continue
        groups.append({
            "classroomId": res["course"]["classroomId"],
            "name": res["course"]["name"],
            "teacher": res["course"]["teacher"],
            "url": course_url(res["course"]),
            "items": res["items"],
        })
    # 未完成的多的排前面
    groups.sort(key=lambda g: -len(g["items"]))
    return {
        "courses": len(courses),
        "groups": groups,
        "total": sum(len(g["items"]) for g in groups),
        "errors": errors,
    }


def chapter_leaves(sessionid, classroom_id):
    """自学章节的 leaf 清单（leaf_type 0 是视频）。"""
    r = http_get(API_BASE + "/mooc-api/v1/lms/learn/course/chapter?cid=%s" % classroom_id,
                 headers=_headers(sessionid), timeout=TIMEOUT)
    data = r.json().get("data") or {}
    leaves = []
    for ch in data.get("course_chapter") or []:
        for sec in ch.get("section_leaf_list") or []:
            for leaf in sec.get("leaf_list") or []:
                leaves.append({
                    "id": leaf.get("id"),
                    "name": leaf.get("name") or "",
                    "isVideo": leaf.get("leaf_type") == 0,
                    "locked": bool(leaf.get("is_locked")),
                    "url": video_url(classroom_id, leaf.get("id")),
                })
    return leaves
