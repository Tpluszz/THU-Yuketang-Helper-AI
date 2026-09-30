# -*- coding: utf-8 -*-
"""把课件每一页的截图按顺序拼成一个 PDF，方便复习。"""
import os
import re

from PIL import Image

from Scripts.Utils import get_output_dir

IMAGE_EXT = (".jpg", ".jpeg", ".png")


def _page_key(name):
    """按文件名里的页码数字排序：2.jpg 要排在 10.jpg 前面。"""
    nums = re.findall(r"\d+", name)
    return (int(nums[0]) if nums else 1 << 30, name)


def slide_images(presentations, output_dir=None):
    """按课件顺序、页码顺序列出本地已下载的截图。"""
    root = output_dir or get_output_dir()
    paths = []
    for pres in presentations or []:
        folder = os.path.join(root, str(pres))
        if not os.path.isdir(folder):
            continue
        names = [n for n in os.listdir(folder) if n.lower().endswith(IMAGE_EXT)]
        for name in sorted(names, key=_page_key):
            paths.append(os.path.join(folder, name))
    return paths


def export_pdf(image_paths, out_path, max_width=1600):
    """拼成 PDF，返回页数。过大的图会等比缩小，控制文件体积。"""
    pages = []
    for path in image_paths:
        try:
            img = Image.open(path)
            img.load()
        except Exception:
            continue          # 个别损坏的截图跳过，不让整份导出失败
        if img.mode != "RGB":
            img = img.convert("RGB")
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, max(1, int(img.height * ratio))), Image.LANCZOS)
        pages.append(img)
    if not pages:
        raise ValueError("没有可导出的课件截图")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    pages[0].save(out_path, "PDF", resolution=150, save_all=True, append_images=pages[1:])
    return len(pages)


def default_pdf_name(lesson_name, started_at=None):
    stamp = (started_at or "")[:10].replace("-", "")
    safe = re.sub(r'[\\/:*?"<>|]+', "_", lesson_name or "课件").strip() or "课件"
    return ("%s_%s.pdf" % (safe, stamp)) if stamp else ("%s.pdf" % safe)
