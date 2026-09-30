/* 界面自检：遍历每个视图与状态，抓尺寸失控、溢出、文字被裁这类问题。
   浏览器里执行 await runAudit() 即可，不参与打包运行。 */
"use strict";

function auditDom(label) {
  const problems = [];
  // 动画进行中测出来的位置不算数：浏览器节流时动画可能长时间不推进
  document.getAnimations().forEach((a) => { try { a.finish(); } catch (e) { /* 无限动画 */ } });
  const vw = document.documentElement.clientWidth;

  // 1) 按钮/导航里的图标不该超过 26px —— 空状态插图那条规则就是这么漏进按钮的
  document.querySelectorAll(".btn svg, .nav-item svg, .chip svg, .x svg").forEach((svg) => {
    const r = svg.getBoundingClientRect();
    if (r.width > 26 || r.height > 26) {
      problems.push(label + "：按钮里的图标过大 " + Math.round(r.width) + "×" + Math.round(r.height) +
        "（" + (svg.closest(".btn, .nav-item, .chip, .x").textContent.trim().slice(0, 12) || "无文字") + "）");
    }
  });

  // 2) 按钮高度失控
  document.querySelectorAll(".btn").forEach((b) => {
    const r = b.getBoundingClientRect();
    if (r.height > 56) {
      problems.push(label + "：按钮过高 " + Math.round(r.height) + "px（" + b.textContent.trim().slice(0, 12) + "）");
    }
  });

  // 3) 横向溢出视口
  document.querySelectorAll("body *").forEach((node) => {
    const r = node.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    if (r.right > vw + 1.5 || r.left < -1.5) {
      const cls = (node.className && String(node.className).split(" ")[0]) || node.tagName;
      problems.push(label + "：元素超出视口 " + cls + "（left=" + Math.round(r.left) +
        " right=" + Math.round(r.right) + " 视口=" + vw + "）");
    }
  });

  // 4) 单行文字被裁（设了 nowrap 却装不下）
  document.querySelectorAll(".stat-value, .stat-sub, .lesson-name, .problem-a, .hist-name, .btn").forEach((node) => {
    const s = getComputedStyle(node);
    if (s.whiteSpace !== "nowrap" && s.textOverflow !== "ellipsis") return;
    if (node.scrollWidth > node.clientWidth + 2 && s.textOverflow !== "ellipsis") {
      problems.push(label + "：文字被裁且没有省略号 " + node.textContent.trim().slice(0, 16));
    }
  });

  // 5) 滚动容器之外出现纵向溢出
  document.querySelectorAll(".card, .modal, .stat, .lesson, .problem").forEach((node) => {
    if (getComputedStyle(node).overflow !== "visible") return;
    if (node.scrollHeight > node.clientHeight + 4 && node.clientHeight > 0) {
      const cls = String(node.className).split(" ")[0];
      problems.push(label + "：内容溢出容器 " + cls + "（内容 " + node.scrollHeight +
        " > 容器 " + node.clientHeight + "）");
    }
  });

  return problems;
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function runAudit() {
  const found = [];
  const seen = [];
  const check = async (label, setup, ms = 420) => {
    document.querySelectorAll(".overlay").forEach((o) => o.remove());
    modalStack = [];
    await setup();
    await wait(ms);
    seen.push(label);
    found.push(...auditDom(label));
  };

  const full = JSON.parse(JSON.stringify(S.lessons));
  const restore = () => { S.lessons = JSON.parse(JSON.stringify(full)); };

  // ---- 课堂页的几种状态
  await check("课堂·未监听无课程", async () => {
    S.state.monitor.active = false; S.lessons = []; switchView("home");
  });
  await check("课堂·未登录", async () => {
    S.state.login.state = "none"; S.state.ai.ready = false; renderHome();
  });
  await check("课堂·监听中无课程", async () => {
    S.state.login.state = "ok"; S.state.ai.ready = true;
    S.state.monitor.active = true; renderHome();
  });
  await check("课堂·有课程", async () => { restore(); renderHome(); });
  await check("课堂·测试模式", async () => {
    S.state.testMode = true; renderShell(); renderHome();
  });
  await check("课堂·长课程名", async () => {
    S.state.testMode = false;
    S.lessons = [Object.assign({}, full[0], {
      name: "马克思主义基本原理概论与中国近现代史纲要联合课程（秋季学期）" })];
    renderHome();
  });
  await check("课堂·无动态", async () => {
    restore(); const logs = S.logs; S.logs = []; renderHome(); S.logs = logs;
  });

  // ---- 题目列表与各题型
  restore();
  await check("题目列表", async () => { await openLessonView("L1"); }, 900);
  for (const f of ["todo", "ready", "done"]) {
    await check("题目列表·筛选" + f, async () => {
      await openLessonView("L1"); S.filter = f; refreshLessonModal();
    }, 800);
  }
  await check("题目列表·批量解题中", async () => {
    await openLessonView("L1");
    renderBatchBar({ lessonId: "L1", done: 3, total: 8, ok: 2, fail: 1, finished: false });
  }, 800);

  const types = { "1": "单选", "2": "多选", "3": "填空", "4": "主观", "5": "已提交" };
  for (const id of Object.keys(types)) {
    await check("答题·" + types[id], async () => {
      await openLessonView("L1"); await wait(500); await openProblemView(id);
    }, 900);
  }

  // ---- 设置
  for (const [key, name] of [["answer", "答题方式"], ["ai", "AI服务"], ["notify", "提醒"], ["misc", "外观"]]) {
    await check("设置·" + name, async () => {
      switchView("settings"); await wait(500);
      const node = document.getElementById("set-" + key);
      if (node) node.scrollIntoView();
    }, 700);
  }
  await check("设置·有未保存改动", async () => {
    switchView("settings"); await wait(500);
    draft.auto_danmu = !draft.auto_danmu; paintSettings();
  }, 700);
  await check("设置·qwen无地址栏", async () => {
    switchView("settings"); await wait(500);
    draft.ai_config.provider = "qwen"; paintSettings();
  }, 700);

  // ---- 历史
  await check("历史·有记录", async () => { switchView("history"); }, 800);

  // ---- 弹窗与提醒
  await check("上手清单", async () => { switchView("home"); await wait(300); showOnboarding(); }, 700);
  await check("确认弹窗", async () => {
    const r = await window.pywebview.api.lesson_detail("L1");
    const p = JSON.parse(JSON.stringify(r.problems[1]));
    p.image = (await window.pywebview.api.problem_image()).image;
    window.__onEvent({ event: "confirm", data: { token: "audit", lessonId: "L1",
      lessonName: "组合数学", problem: p, answers: ["A", "B"], timeout: 30 } });
  }, 800);
  await check("扫码登录", async () => { openLoginModal(); }, 600);
  await check("浮窗提醒", async () => {
    switchView("home"); await wait(300);
    showToast({ title: "新题目：组合数学", message: "第4页 单选题，剩余 60 秒", urgent: false });
    showToast({ title: "点到你了！", message: "组合数学 正在点名，点到了你（唐琦）", urgent: true });
  }, 600);

  document.querySelectorAll(".overlay").forEach((o) => o.remove());
  document.querySelectorAll(".toast").forEach((o) => o.remove());
  modalStack = [];
  restore();
  return { checked: seen.length, states: seen, problems: found };
}
