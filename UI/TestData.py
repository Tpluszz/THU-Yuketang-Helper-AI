# -*- coding: utf-8 -*-
"""测试模式用的假数据：不联网、不签到，纯粹用来熟悉界面操作。"""
import os
import threading

from Scripts.Classes import Lesson
from Scripts.Utils import get_output_dir

TEST_LESSON_ID = "test_lesson_1"

test_course = {
    "lessonId": TEST_LESSON_ID,
    "courseName": "示例课程（测试模式）",
    "classroomId": "test_classroom_1",
    "status": 1,
}


def load_test_problems():
    """覆盖单选 / 多选 / 填空 / 主观四种题型的示例题目。"""
    return [
        {
            "problemId": "test_single",
            "problemType": 1,
            "body": "下列哪一项是 Python 中用于定义函数的关键字？",
            "options": [
                {"key": "A", "value": "func"},
                {"key": "B", "value": "def"},
                {"key": "C", "value": "function"},
                {"key": "D", "value": "lambda"},
            ],
            "answers": [],
            "page": 1,
        },
        {
            "problemId": "test_multi",
            "problemType": 2,
            "body": "以下哪些属于 Python 的内置数据类型？（多选）",
            "options": [
                {"key": "A", "value": "list"},
                {"key": "B", "value": "dict"},
                {"key": "C", "value": "vector"},
                {"key": "D", "value": "tuple"},
            ],
            "answers": [],
            "page": 2,
        },
        {
            "problemId": "test_blank",
            "problemType": 4,
            "body": "填空：HTTP 状态码 ____ 表示未找到资源，____ 表示服务器内部错误。",
            "blanks": ["", ""],
            "answers": [],
            "page": 3,
        },
        {
            "problemId": "test_subjective",
            "problemType": 5,
            "body": "请简述你对「课堂互动工具」的看法。",
            "answers": [],
            "page": 4,
        },
        {
            "problemId": "test_locked",
            "problemType": 1,
            "body": "这道题演示「已提交」状态，界面上会被锁定，不能再修改。",
            "options": [
                {"key": "A", "value": "可以修改"},
                {"key": "B", "value": "不能修改"},
            ],
            "answers": ["B"],
            "result": ["B"],
            "page": 5,
        },
    ]


def get_test_lessons():
    """课程表格用的原始课程数据。"""
    return [dict(test_course)]


class TestLesson(Lesson):
    """和 Lesson 接口一致，但完全不联网的假课程。"""

    def __init__(self, main_ui):
        self.classroomid = test_course["classroomId"]
        self.lessonid = TEST_LESSON_ID
        self.lessonname = test_course["courseName"]
        self.sessionid = ""
        self.headers = {}
        self.receive_danmu = {}
        self.sent_danmu_dict = {}
        self.danmu_dict = {}
        self.problems_ls = load_test_problems()
        self.unlocked_problem = []
        self.classmates_ls = []
        self.finished = False
        self.stopped = False
        self.wsapp = None
        self.add_message = main_ui.add_message
        self.config = main_ui.config
        self.main_ui = main_ui
        self._lock = threading.RLock()
        self.user_uid = 0
        self.user_uname = "测试用户"
        self._prepare_images()

    def _prepare_images(self):
        """为每道示例题渲染一张占位截图，方便预览详情页的排版。"""
        folder = os.path.join(get_output_dir(), "test")
        os.makedirs(folder, exist_ok=True)
        for problem in self.problems_ls:
            path = os.path.join(folder, "%s.png" % problem["problemId"])
            problem["image"] = path if self._render_placeholder(problem, path) else ""

    @staticmethod
    def _render_placeholder(problem, path):
        if os.path.exists(path):
            return True
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return False
        try:
            image = Image.new("RGB", (900, 560), "#FFFFFF")
            draw = ImageDraw.Draw(image)
            draw.rectangle([0, 0, 899, 70], fill="#7A1F8C")
            draw.text((28, 28), "Sample slide  /  page %s" % problem.get("page"), fill="#FFFFFF")
            draw.text((28, 120), problem.get("body", "")[:60], fill="#1F2328")
            y = 190
            for option in problem.get("options", []):
                draw.ellipse([28, y, 44, y + 16], outline="#7A1F8C", width=2)
                draw.text((60, y), "%s. %s" % (option.get("key"), option.get("value")), fill="#1F2328")
                y += 46
            draw.text((28, 500), "这是测试模式生成的占位图，不是真实课件。", fill="#9AA1AC")
            image.save(path)
            return True
        except Exception:
            return False

    # --- 下面这些操作在测试模式下只做提示，不发任何网络请求

    def start_lesson(self, callback):
        self.add_message("测试课程无需签到，可直接双击课程查看题目", 0)
        return callback(self)

    def checkin_class(self):
        return "test-token"

    def submit_problem(self, problem):
        problem["result"] = problem.get("answers") or []
        self.notify_update()
        self.add_message("【测试模式】第%s页已模拟提交，未发送到雨课堂" % problem.get("page"), 7)
        return True

    def answer_questions(self, problemid, problemtype, answer, limit):
        self.add_message("【测试模式】模拟提交答案：%s" % (answer,), 7)
        return True

    def send_danmu(self, content):
        self.add_message("【测试模式】模拟发送弹幕：%s" % content, 7)

    def stop(self):
        self.stopped = True


def create_test_lesson(main_ui):
    """创建测试课程对象。"""
    return TestLesson(main_ui)
