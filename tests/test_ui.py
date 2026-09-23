import sys, os, tkinter as tk
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 用临时配置目录，避免碰用户真实配置
import tempfile
tmp = tempfile.mkdtemp()
os.environ["HOME"] = tmp
os.makedirs(os.path.join(tmp, "Library"), exist_ok=True)

from UI.MainWindow import MainWindow
from UI.ProblemListWindow import ProblemListWindow
from UI.ProblemDetailWindow import ProblemDetailWindow
from UI.Config import ConfigDialog

root = tk.Tk()
app = MainWindow(root)
root.update()
print("main window ok, theme =", app.mode)

# 测试模式
app.toggle_test_mode()
root.update()
print("test mode ok, rows =", len(app.tree.get_children()))

lesson = app.on_lesson_list[0]
plw = ProblemListWindow(root, lesson, app)
root.update()
print("problem list ok, rows =", len(plw.tree.get_children()))

for idx, prob in enumerate(lesson.snapshot_problems()):
    d = ProblemDetailWindow(plw.window, prob, lesson, plw)
    root.update()
    d.apply_answers(["B"] if prob.get("options") else ["404", "500"])
    print("  detail", prob["problemId"], "collect ->", d.collect_answers())
    if not d.locked:
        d.on_save_click()
    d.close()
root.update()
plw.refresh()
print("after save, badge:", plw.done_badge.cget("text"))

cfg = ConfigDialog(root, app)
root.update()
cfg.ai_key_var.set("sk-test"); cfg.theme_var.set("dark")
cfg.save_config()
root.update()
print("config saved ->", app.config["ai_config"]["api_key"], app.config["ui_theme"], "theme_changed:", cfg.theme_changed)

app.add_message("测试错误消息", 4); app.add_message("测试警告", 8); app.add_message("点到你了", 5)
root.update()
plw.close()
app.toggle_test_mode()
root.update()
print("exit test mode ok, rows =", len(app.tree.get_children()))
root.destroy()
print("ALL OK")
