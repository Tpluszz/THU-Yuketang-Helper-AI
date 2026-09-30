/* 雨课堂助手 — 前端。与 Python 的通信全部走 window.pywebview.api。 */
"use strict";

// ============================================================ 与 Python 通信

const api = new Proxy({}, {
  get: (_, name) => async (...args) => {
    const bridge = window.pywebview && window.pywebview.api;
    if (!bridge || typeof bridge[name] !== "function") {
      return { ok: false, error: "接口 " + String(name) + " 不可用" };
    }
    try {
      return await bridge[name](...args);
    } catch (err) {
      return { ok: false, error: String((err && err.message) || err) };
    }
  },
});

// ============================================================ 全局状态

const S = {
  view: "home",
  state: null,
  lessons: [],
  logs: [],
  meta: null,
  settings: null,
  batch: {},          // lessonId -> 批量解题进度
  openLesson: null,   // 当前打开的题目列表
  filter: "all",
  ready: false,
};

// ============================================================ DOM 工具

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function esc(text) {
  return String(text == null ? "" : text)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function el(html) {
  const tpl = document.createElement("template");
  tpl.innerHTML = html.trim();
  return tpl.content.firstElementChild;
}

function icon(name) {
  const paths = {
    play: '<path d="M7 4.5v15l12-7.5z"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    refresh: '<path d="M3.5 12a8.5 8.5 0 1 0 2.5-6M3 4v4h4"/>',
    sparkle: '<path d="M12 3.5 13.6 9 19 10.5 13.6 12 12 17.5 10.4 12 5 10.5 10.4 9z"/><path d="M18.5 3.5v3M20 5h-3"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    download: '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19h14"/>',
    trash: '<path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/>',
    book: '<path d="M4 5h16v11H4zM8 20h8M12 16v4"/>',
    clock: '<path d="M12 7v5l3 2M3.5 12a8.5 8.5 0 1 0 2.5-6M3 4v4h4"/>',
    back: '<path d="M14 6l-6 6 6 6"/>',
    external: '<path d="M14 4h6v6M20 4l-8 8M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    folder: '<path d="M4 6h5l2 2h9v10H4z"/>',
    bell: '<path d="M18 9a6 6 0 0 0-12 0c0 6-2 7-2 7h16s-2-1-2-7M10.5 20a2 2 0 0 0 3 0"/>',
  };
  return '<svg class="icon" viewBox="0 0 24 24">' + (paths[name] || "") + "</svg>";
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const p = (n) => String(n).padStart(2, "0");
  return p(d.getHours()) + ":" + p(d.getMinutes());
}

function fmtDate(iso) {
  if (!iso) return "未知日期";
  const d = new Date(iso);
  if (isNaN(d)) return "未知日期";
  const today = new Date();
  const same = (a, b) => a.toDateString() === b.toDateString();
  const yest = new Date(today.getTime() - 86400000);
  if (same(d, today)) return "今天";
  if (same(d, yest)) return "昨天";
  return d.getFullYear() + "年" + (d.getMonth() + 1) + "月" + d.getDate() + "日";
}

// ============================================================ 浮窗提醒

function showToast(t) {
  const box = $("#toasts");
  const node = el(
    '<div class="toast' + (t.urgent ? " urgent" : "") + '">' +
      '<div class="tt">' + esc(t.title) + "</div>" +
      '<div class="tm">' + esc(t.message) + "</div>" +
    "</div>");
  node.onclick = () => {
    dismiss(node);
    if (t.target && t.target.lessonId) {
      openLessonView(t.target.lessonId, t.target.problemId);
    }
  };
  box.appendChild(node);
  while (box.children.length > 4) dismiss(box.firstElementChild);
  // 紧急提醒（点名）不自动消失，必须点掉
  if (!t.urgent) setTimeout(() => dismiss(node), 7000);
}

function dismiss(node) {
  if (!node || !node.parentNode) return;
  node.classList.add("out");
  setTimeout(() => node.remove(), 200);
}

// ============================================================ 弹窗

let modalStack = [];

function openModal(html, opts = {}) {
  const overlay = el('<div class="overlay"></div>');
  const modal = el('<div class="modal ' + (opts.size || "md") + '"></div>');
  modal.innerHTML = html;
  overlay.appendChild(modal);
  overlay.onclick = (e) => {
    if (e.target === overlay && !opts.sticky) closeModal(overlay);
  };
  $("#modal-root").appendChild(overlay);
  modalStack.push({ overlay, opts });
  if (opts.onClose) overlay.__onClose = opts.onClose;
  const focus = modal.querySelector("[autofocus]");
  if (focus) setTimeout(() => focus.focus(), 30);
  return modal;
}

function closeModal(overlay) {
  const top = modalStack[modalStack.length - 1];
  const target = overlay || (top && top.overlay);
  if (!target) return;
  modalStack = modalStack.filter((m) => m.overlay !== target);
  if (target.__onClose) target.__onClose();
  target.remove();
}

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || !modalStack.length) return;
  const top = modalStack[modalStack.length - 1];
  if (!top.opts.sticky) closeModal(top.overlay);
});

function toastMsg(message, tone) {
  showToast({ title: tone === "error" ? "出错了" : "提示", message, urgent: false });
}

// ============================================================ 事件入口（Python 调用）

window.__onEvent = function (payload) {
  const { event, data } = payload;
  if (event === "state") {
    S.state = data;
    renderShell();
    if (S.view === "home") renderHome();
  } else if (event === "lessons") {
    S.lessons = data || [];
    if (S.view === "home") renderHome();
    if (S.openLesson) refreshLessonModal();
  } else if (event === "log") {
    S.logs.push(data);
    if (S.logs.length > 600) S.logs.shift();
    appendLog(data);
  } else if (event === "lesson_updated") {
    if (S.openLesson && S.openLesson.id === data.id) refreshLessonModal();
  } else if (event === "toast") {
    showToast(data);
  } else if (event === "batch") {
    S.batch[data.lessonId] = data;
    if (data.finished) delete S.batch[data.lessonId];
    if (S.openLesson && S.openLesson.id === data.lessonId) {
      renderBatchBar(data);
      if (data.finished) refreshLessonModal();
    }
  } else if (event === "confirm") {
    showConfirmModal(data);
  } else if (event === "confirm_closed") {
    closeConfirmModal(data.token);
  } else if (event === "login") {
    onLoginEvent(data);
  }
};

// ============================================================ 侧边栏

const LOGIN_UI = {
  checking: { color: "var(--faint)", who: "正在检查……", sub: "确认登录状态" },
  ok:       { color: "var(--success)", who: "", sub: "已登录" },
  none:     { color: "var(--danger)", who: "未登录", sub: "点这里扫码登录" },
  expired:  { color: "var(--warning)", who: "登录已过期", sub: "点这里重新登录" },
  offline:  { color: "var(--warning)", who: "网络异常", sub: "暂时无法确认登录" },
};

function renderShell() {
  const st = S.state;
  if (!st) return;
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === S.view));

  const ui = LOGIN_UI[st.login.state] || LOGIN_UI.checking;
  const who = st.login.state === "ok" ? (st.login.name || "已登录") : ui.who;
  $("#account").innerHTML =
    '<span class="dot" style="background:' + ui.color + '"></span>' +
    '<span style="min-width:0"><span class="who">' + esc(who) + "</span>" +
    '<div class="sub">' + esc(ui.sub) + "</div></span>";

  const toggle = $("#test-toggle");
  toggle.checked = !!st.testMode;
  toggle.disabled = !!st.monitor.active;
  toggle.parentElement.title = st.monitor.active ? "请先停止监听" : "用示例题目熟悉操作，不会发到雨课堂";
}

// ============================================================ 课堂主页

function renderHome() {
  if (S.view !== "home") return;
  const st = S.state;
  if (!st) return;
  const active = st.monitor.active;
  const live = S.lessons.filter((l) => l.status === "live" || l.status === "test");

  $("#main").innerHTML =
    '<div class="page">' +
      '<div class="page-head">' +
        '<h1 class="page-title">课堂</h1>' +
        (st.testMode ? '<span class="pill warning">测试模式</span>' : "") +
        '<div class="spacer"></div>' +
        '<button class="btn ' + (active ? "danger" : "primary") + '" data-act="toggle-monitor">' +
          icon(active ? "stop" : "play") + (active ? "停止监听" : "启动监听") +
        "</button>" +
      "</div>" +
      renderStats() +
      '<div class="section">' +
        '<div class="section-head"><h2 class="section-title">课程</h2>' +
          (active ? '<span class="pill success live"><span class="dot"></span>' + esc(st.monitor.text) + "</span>" : "") +
        "</div>" +
        (S.lessons.length ? '<div class="lessons">' + S.lessons.map(lessonCard).join("") + "</div>"
                          : emptyLessons(active, st)) +
      "</div>" +
      '<div class="section">' +
        '<div class="section-head"><h2 class="section-title">动态</h2><div class="spacer"></div>' +
          '<button class="btn ghost sm" data-act="clear-log">清空</button></div>' +
        '<div class="card"><div class="log" id="log"></div></div>' +
      "</div>" +
    "</div>";

  renderLog();
  void live;
}

function renderStats() {
  const st = S.state;
  const totals = S.lessons.reduce((acc, l) => {
    acc.problems += l.problemCount;
    acc.submitted += l.submitted;
    acc.ready += l.ready;
    return acc;
  }, { problems: 0, submitted: 0, ready: 0 });

  const loginBad = st.login.state === "none" || st.login.state === "expired";
  const loginUi = LOGIN_UI[st.login.state] || LOGIN_UI.checking;

  const cards = [
    {
      cls: loginBad ? "bad" : "",
      act: loginBad ? "login" : "",
      label: "登录", dot: loginUi.color,
      value: st.login.state === "ok" ? (st.login.name || "已登录") : loginUi.who,
      sub: st.login.state === "ok" ? "雨课堂账号正常" : loginUi.sub,
    },
    {
      cls: st.ai.ready ? "" : "warn", act: "settings-ai",
      label: "AI", dot: st.ai.ready ? "var(--success)" : "var(--warning)",
      value: st.ai.ready ? st.ai.model : "未配置",
      sub: st.ai.ready ? st.ai.provider : "点这里去配置",
    },
    {
      cls: "", act: "settings-answer", label: "答题方式", dot: "var(--accent)",
      value: st.mode.label, sub: "推题时怎么处理",
    },
    {
      cls: "", act: "", label: "本次监听", dot: totals.problems ? "var(--accent)" : "var(--faint)",
      value: totals.problems + " 道题",
      sub: totals.problems ? ("已交 " + totals.submitted + " · 待交 " + totals.ready) : "还没收到题目",
    },
  ];

  return '<div class="stats">' + cards.map((c) => {
    const tag = c.act ? "button" : "div";
    return "<" + tag + ' class="stat ' + c.cls + '"' + (c.act ? ' data-act="' + c.act + '"' : "") + ">" +
      '<div class="stat-label"><span class="dot" style="background:' + c.dot + '"></span>' + esc(c.label) + "</div>" +
      '<div class="stat-value">' + esc(c.value) + "</div>" +
      '<div class="stat-sub">' + esc(c.sub) + "</div>" +
    "</" + tag + ">";
  }).join("") + "</div>";
}

function lessonCard(l) {
  const pillCls = { live: "success live", finished: "", test: "warning", pending: "info" }[l.status] || "";
  const total = Math.max(1, l.problemCount);
  const sPct = (l.submitted / total) * 100;
  const rPct = (l.ready / total) * 100;
  return (
    '<div class="lesson card" data-act="open-lesson" data-id="' + esc(l.id) + '">' +
      '<div class="lesson-top">' +
        '<div class="lesson-name">' + esc(l.name) + "</div>" +
        '<span class="pill ' + pillCls + '">' + (l.status === "live" ? '<span class="dot"></span>' : "") + esc(l.statusText) + "</span>" +
      "</div>" +
      '<div class="lesson-nums">' +
        '<div class="num"><b>' + l.problemCount + "</b><span>题目</span></div>" +
        '<div class="num"><b style="color:var(--success)">' + l.submitted + "</b><span>已提交</span></div>" +
        '<div class="num"><b style="color:var(--accent)">' + l.ready + "</b><span>待提交</span></div>" +
      "</div>" +
      (l.problemCount
        ? '<div class="lesson-bar"><i class="s" style="width:' + sPct + '%"></i><i class="r" style="width:' + rPct + '%"></i></div>'
        : "") +
      '<div class="lesson-actions">' +
        '<button class="btn sm" data-act="open-lesson" data-id="' + esc(l.id) + '">' + icon("book") + "查看题目</button>" +
        (l.slides ? '<button class="btn sm" data-act="export-pdf" data-id="' + esc(l.id) + '">' + icon("download") + "课件 PDF</button>" : "") +
      "</div>" +
    "</div>");
}

function emptyLessons(active, st) {
  const needLogin = st.login.state !== "ok";
  return (
    '<div class="empty">' +
      '<svg viewBox="0 0 24 24"><path d="M4 5h16v11H4zM8 20h8M12 16v4"/></svg>' +
      "<h3>" + (active ? "正在等待上课" : "还没有开始监听") + "</h3>" +
      "<p>" + (active
        ? "检测到你的课开始后，会自动签到并把题目收进来"
        : (needLogin ? "先登录雨课堂，再启动监听" : "点「启动监听」开始，或用测试模式先熟悉一下")) + "</p>" +
      '<div class="actions">' +
        (needLogin ? '<button class="btn primary" data-act="login">扫码登录</button>' : "") +
        (!active && !needLogin ? '<button class="btn primary" data-act="toggle-monitor">' + icon("play") + "启动监听</button>" : "") +
        (!active ? '<button class="btn" data-act="test-mode-on">试用示例课程</button>' : "") +
      "</div>" +
    "</div>");
}

// ============================================================ 日志

function renderLog() {
  const box = $("#log");
  if (!box) return;
  if (!S.logs.length) {
    box.innerHTML = '<div class="log-empty">还没有动态</div>';
    return;
  }
  box.innerHTML = S.logs.slice(-200).map(logRow).join("");
  box.scrollTop = box.scrollHeight;
}

function logRow(e) {
  // 等级类名统一加 lv- 前缀：level 里有 "lesson"，会和课程卡片的 .lesson 撞车
  return '<div class="log-row lv-' + esc(e.level) + '">' +
    '<span class="log-t">' + esc(e.t) + "</span>" +
    '<span class="log-dot"></span>' +
    '<span class="log-text selectable">' + esc(e.text) + "</span></div>";
}

function appendLog(e) {
  const box = $("#log");
  if (!box) return;
  if (box.querySelector(".log-empty")) box.innerHTML = "";
  const near = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  box.insertAdjacentHTML("beforeend", logRow(e));
  while (box.children.length > 200) box.firstElementChild.remove();
  if (near) box.scrollTop = box.scrollHeight;
}

// ============================================================ 题目列表

async function openLessonView(lessonId, problemId) {
  const res = await api.lesson_detail(lessonId);
  if (!res.ok) { toastMsg(res.error, "error"); return; }
  S.openLesson = res;
  S.filter = "all";

  const modal = openModal(
    '<div class="modal-head">' +
      '<h2 class="modal-title" id="lm-title"></h2>' +
      '<div class="spacer"></div>' +
      '<button class="x" data-act="close-modal">' + icon("close") + "</button>" +
    "</div>" +
    '<div class="modal-body" id="lm-body"></div>', { size: "lg", onClose: () => { S.openLesson = null; } });

  modal.id = "lesson-modal";
  refreshLessonModal();
  if (problemId) {
    const p = res.problems.find((x) => String(x.id) === String(problemId));
    if (p) openProblemView(p.id);
  }
}

function refreshLessonModal() {
  if (!S.openLesson) return;
  api.lesson_detail(S.openLesson.id).then((res) => {
    if (!res.ok || !S.openLesson) return;
    S.openLesson = res;
    const title = $("#lm-title");
    if (!title) return;
    title.innerHTML = esc(res.name) +
      (res.readonly ? ' <span class="pill">历史记录</span>' : "") +
      (res.test ? ' <span class="pill warning">测试</span>' : "");
    $("#lm-body").innerHTML = lessonBody(res);
    const batch = S.batch[res.id];
    if (batch) renderBatchBar(batch);
    loadThumbs(res);
  });
}

function lessonBody(res) {
  const ps = res.problems;
  const counts = {
    all: ps.length,
    todo: ps.filter((p) => !p.submitted && !p.answers.length).length,
    ready: ps.filter((p) => !p.submitted && p.answers.length).length,
    done: ps.filter((p) => p.submitted).length,
  };
  const chip = (k, label) =>
    '<button class="chip' + (S.filter === k ? " active" : "") + '" data-act="filter" data-k="' + k + '">' +
      label + '<span class="n">' + counts[k] + "</span></button>";

  const list = ps.filter((p) => {
    if (S.filter === "todo") return !p.submitted && !p.answers.length;
    if (S.filter === "ready") return !p.submitted && p.answers.length;
    if (S.filter === "done") return p.submitted;
    return true;
  });

  return (
    '<div class="toolbar">' +
      '<div class="chips">' + chip("all", "全部") + chip("todo", "未作答") +
        chip("ready", "待提交") + chip("done", "已提交") + "</div>" +
      '<div class="spacer"></div>' +
      (res.slides ? '<button class="btn sm" data-act="export-pdf" data-id="' + esc(res.id) + '">' +
        icon("download") + "课件 PDF（" + res.slides + " 页）</button>" : "") +
      (counts.todo ? '<button class="btn sm primary" data-act="solve-all">' + icon("sparkle") +
        "AI 解答 " + counts.todo + " 道未答题</button>" : "") +
    "</div>" +
    '<div id="batch-bar"></div>' +
    (list.length ? '<div class="problems">' + list.map(problemCard).join("") + "</div>"
      : '<div class="empty"><h3>这里空着</h3><p>' +
        (ps.length ? "换个筛选看看" : "老师放出课件后题目会自动出现") + "</p></div>"));
}

function problemCard(p) {
  const badge = p.submitted
    ? '<span class="pill success">已提交</span>'
    : (p.answers.length ? '<span class="pill accent">待提交</span>' : '<span class="pill">未作答</span>');
  return (
    '<div class="problem card' + (p.submitted ? " submitted" : "") + '" data-act="open-problem" data-id="' + esc(p.id) + '">' +
      '<div class="thumb" data-thumb="' + esc(p.id) + '">' +
        '<span class="page">第 ' + esc(p.page) + " 页</span>" +
        (p.hasImage ? "" : "无截图") +
      "</div>" +
      '<div class="problem-body">' +
        '<div class="problem-meta"><span class="pill">' + esc(p.type) + "</span>" + badge +
          (p.explanation ? '<span class="pill info">有讲解</span>' : "") + "</div>" +
        '<div class="problem-q">' + esc(p.body || "（无文字题干，见截图）") + "</div>" +
        '<div class="problem-a' + (p.answers.length ? "" : " none") + '">' +
          (p.answers.length ? "答案：" + esc(p.answerText) : "尚无答案") + "</div>" +
      "</div>" +
    "</div>");
}

// 缩略图逐张异步加载，避免一次性把几十张图塞进一次调用
async function loadThumbs(res) {
  for (const p of res.problems) {
    if (!p.hasImage) continue;
    const box = document.querySelector('[data-thumb="' + CSS.escape(String(p.id)) + '"]');
    if (!box || box.querySelector("img")) continue;
    const r = await api.problem_image(res.id, p.id, 420);
    if (!r.ok || !r.image) continue;
    const still = document.querySelector('[data-thumb="' + CSS.escape(String(p.id)) + '"]');
    if (!still || still.querySelector("img")) continue;
    const img = el('<img alt="">');
    img.src = r.image;
    still.insertBefore(img, still.firstChild);
  }
}

function renderBatchBar(b) {
  const box = $("#batch-bar");
  if (!box) return;
  if (b.finished) {
    box.innerHTML = "";
    return;
  }
  const pct = b.total ? (b.done / b.total) * 100 : 0;
  box.innerHTML =
    '<div class="batch card">' +
      '<span class="btn-spin"><span class="spin" style="width:14px;height:14px;border:2px solid var(--accent);border-right-color:transparent;border-radius:50%;display:inline-block;animation:spin .7s linear infinite"></span></span>' +
      '<div style="flex:1"><div style="font-size:13px;margin-bottom:6px">AI 解答中 ' + b.done + " / " + b.total +
        (b.fail ? '　<span style="color:var(--danger)">失败 ' + b.fail + "</span>" : "") + "</div>" +
        '<div class="progress"><i style="width:' + pct + '%"></i></div></div>' +
      '<button class="btn sm" data-act="cancel-solve-all">停止</button>' +
    "</div>";
}

// ============================================================ 单题作答

let answerDraft = null;

async function openProblemView(problemId) {
  const lesson = S.openLesson;
  if (!lesson) return;
  const p = lesson.problems.find((x) => String(x.id) === String(problemId));
  if (!p) return;

  answerDraft = { answers: p.answers.slice(), problem: p, lessonId: lesson.id };
  const locked = p.submitted || lesson.readonly;

  const modal = openModal(
    '<div class="modal-head">' +
      '<h2 class="modal-title">第 ' + esc(p.page) + " 页</h2>" +
      '<span class="pill accent">' + esc(p.type) + "</span>" +
      (p.submitted ? '<span class="pill success">已提交 · 不可修改</span>' : "") +
      '<div class="spacer"></div>' +
      '<button class="x" data-act="close-modal">' + icon("close") + "</button>" +
    "</div>" +
    '<div class="detail">' +
      '<div class="detail-img" id="pd-img"><span class="none">' +
        (p.hasImage ? "正在加载截图……" : "这道题没有截图") + "</span></div>" +
      '<div class="detail-side">' +
        '<div class="detail-q selectable">' + esc(p.body || "（无文字题干，请看左侧截图）") + "</div>" +
        '<div id="pd-answer"></div>' +
        '<div id="pd-notes"></div>' +
      "</div>" +
    "</div>" +
    '<div class="modal-foot">' +
      (locked ? "" :
        '<button class="btn" data-act="ai-solve">' + icon("sparkle") + "AI 作答</button>" +
        '<button class="btn" data-act="ai-review">' + icon("check") + "复核</button>") +
      '<button class="btn" data-act="ai-explain">' + icon("book") + "讲解思路</button>" +
      '<div class="spacer"></div>' +
      '<span class="hint" id="pd-status"></span>' +
      (locked ? '<button class="btn" data-act="close-modal">关闭</button>' :
        '<button class="btn" data-act="save-answer">保存</button>' +
        '<button class="btn primary" data-act="submit-answer">提交到雨课堂</button>') +
    "</div>", { size: "lg" });

  modal.id = "problem-modal";
  renderAnswerArea();
  renderNotes(p);

  if (p.hasImage) {
    const r = await api.problem_image(lesson.id, p.id, 1400);
    const box = $("#pd-img");
    if (box && r.ok && r.image) {
      box.innerHTML = "";
      const img = el('<img alt="题目截图">');
      img.src = r.image;
      box.appendChild(img);
    } else if (box) {
      box.innerHTML = '<span class="none">截图加载失败</span>';
    }
  }
}

function renderAnswerArea() {
  const box = $("#pd-answer");
  if (!box || !answerDraft) return;
  const p = answerDraft.problem;
  const locked = p.submitted || (S.openLesson && S.openLesson.readonly);
  const cur = answerDraft.answers;
  let html = '<div class="label" style="margin-bottom:8px">你的答案</div>';

  if (p.widget === "single" || p.widget === "multi") {
    const multi = p.widget === "multi";
    html += '<div class="answer-list">' + p.options.map((o) => {
      const on = cur.indexOf(o.key) >= 0;
      return '<label class="opt' + (on ? " on" : "") + (locked ? " locked" : "") + '" data-act="pick" data-key="' +
        esc(o.key) + '">' +
        '<span class="mark ' + (multi ? "square" : "round") + '">' + (multi ? "✓" : "●") + "</span>" +
        '<span class="v"><span class="k">' + esc(o.key) + ".</span>" + esc(o.value) + "</span></label>";
    }).join("") + "</div>";
  } else if (p.widget === "text") {
    html += '<textarea class="textarea" id="ans-text" ' + (locked ? "disabled" : "") +
      ' placeholder="写下你的作答">' + esc(cur[0] || "") + "</textarea>";
  } else {
    html += '<div class="answer-list">';
    for (let i = 0; i < p.blanks; i++) {
      html += '<div class="blank-row"><span class="label">填空 ' + (i + 1) + "</span>" +
        '<input class="input" data-blank="' + i + '" value="' + esc(cur[i] || "") + '" ' +
        (locked ? "disabled" : "") + "></div>";
    }
    html += "</div>";
  }
  box.innerHTML = html;

  if (!locked) {
    const ta = $("#ans-text");
    if (ta) ta.oninput = () => { answerDraft.answers = ta.value.trim() ? [ta.value] : []; };
    $$("[data-blank]", box).forEach((inp) => {
      inp.oninput = () => {
        const vals = $$("[data-blank]", box).map((x) => x.value.trim());
        while (vals.length && !vals[vals.length - 1]) vals.pop();
        answerDraft.answers = vals;
      };
    });
  }
}

function pickOption(key) {
  if (!answerDraft) return;
  const p = answerDraft.problem;
  if (p.submitted || (S.openLesson && S.openLesson.readonly)) return;
  if (p.widget === "multi") {
    const i = answerDraft.answers.indexOf(key);
    if (i >= 0) answerDraft.answers.splice(i, 1);
    else answerDraft.answers.push(key);
    answerDraft.answers.sort();
  } else {
    answerDraft.answers = [key];
  }
  renderAnswerArea();
}

function renderNotes(p) {
  const box = $("#pd-notes");
  if (!box) return;
  let html = "";
  if (p.explanation) {
    html += '<div class="note accent"><div class="nh">' + icon("book") + "解题思路</div>" +
      '<div class="nb selectable">' + esc(p.explanation) + "</div></div>";
  }
  if (p.review) {
    const agreed = p.review.ok;
    html += '<div class="note ' + (agreed ? "success" : "warning") + '">' +
      '<div class="nh">' + icon("check") + (agreed ? "复核：答案没问题" : "复核：建议改成 " + esc((p.review.answer || []).join("、"))) + "</div>" +
      (p.review.reason ? '<div class="nb selectable">' + esc(p.review.reason) + "</div>" : "") + "</div>";
  }
  box.innerHTML = html;
}

function setStatus(text, tone) {
  const box = $("#pd-status");
  if (box) {
    box.textContent = text || "";
    box.style.color = tone === "error" ? "var(--danger)" : tone === "ok" ? "var(--success)" : "var(--muted)";
  }
}

async function busy(selector, fn) {
  const btn = $(selector);
  const old = btn ? btn.innerHTML : null;
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin"></span>处理中'; }
  try { return await fn(); }
  finally { if (btn && old !== null) { btn.disabled = false; btn.innerHTML = old; } }
}

// ============================================================ 扫码登录

let loginOverlay = null;

function openLoginModal() {
  const modal = openModal(
    '<div class="modal-head"><h2 class="modal-title">扫码登录雨课堂</h2><div class="spacer"></div>' +
      '<button class="x" data-act="close-login">' + icon("close") + "</button></div>" +
    '<div class="modal-body">' +
      '<div class="qr-box">' +
        '<div class="qr-frame" id="qr-frame"><span class="ph">正在获取二维码……</span></div>' +
        '<div class="qr-status" id="qr-status">请稍候</div>' +
        '<div class="hint" style="text-align:center;max-width:300px">' +
          "扫码只用于获取你的登录状态，账号信息不会发给任何第三方。二维码 60 秒自动更新。</div>" +
      "</div>" +
    "</div>" +
    '<div class="modal-foot"><div class="spacer"></div>' +
      '<button class="btn" data-act="login-refresh">' + icon("refresh") + "换一张</button>" +
      '<button class="btn" data-act="close-login">取消</button></div>',
    { size: "sm", sticky: true, onClose: () => { loginOverlay = null; api.login_cancel(); } });

  loginOverlay = modalStack[modalStack.length - 1].overlay;
  api.login_start();
  return modal;
}

function onLoginEvent(ev) {
  if (!loginOverlay) return;
  if (ev.type === "qr") {
    const frame = $("#qr-frame");
    if (frame) frame.innerHTML = '<img src="' + ev.image + '" alt="登录二维码">';
  } else if (ev.type === "status") {
    const box = $("#qr-status");
    if (box) { box.textContent = ev.text; box.className = "qr-status " + (ev.tone || ""); }
  } else if (ev.type === "done") {
    const box = $("#qr-status");
    if (box) { box.textContent = "登录成功"; box.className = "qr-status success"; }
    setTimeout(() => { if (loginOverlay) closeModal(loginOverlay); }, 700);
  }
}

// ============================================================ AI 答完的确认弹窗

const confirmTimers = {};

function showConfirmModal(data) {
  const p = data.problem;
  const modal = openModal(
    '<div class="modal-head"><h2 class="modal-title">AI 答完了，要提交吗？</h2>' +
      '<span class="pill accent">' + esc(p.type) + "</span>" +
      '<div class="spacer"></div></div>' +
    '<div class="modal-body">' +
      '<div class="hint" style="margin-bottom:10px">' + esc(data.lessonName) + " · 第 " + esc(p.page) + " 页</div>" +
      (p.image ? '<img class="confirm-img" src="' + p.image + '" alt="题目">' : "") +
      '<div class="note accent" style="margin-top:12px"><div class="nh">AI 给出的答案</div>' +
        '<div class="nb" style="font-size:15px;font-weight:650;color:var(--text)">' +
        esc(data.answers.join("、")) + "</div></div>" +
      '<div id="cf-edit" style="margin-top:12px"></div>' +
    "</div>" +
    '<div class="modal-foot">' +
      '<div class="countdown" id="cf-count"></div>' +
      '<div class="spacer"></div>' +
      '<button class="btn" data-act="confirm-no" data-token="' + esc(data.token) + '">不提交</button>' +
      '<button class="btn primary" autofocus data-act="confirm-yes" data-token="' + esc(data.token) + '">确认提交</button>' +
    "</div>", { size: "md", sticky: true });

  modal.dataset.token = data.token;

  // 选择题允许当场改答案
  if (p.widget === "single" || p.widget === "multi") {
    const picked = data.answers.slice();
    const box = $("#cf-edit");
    const paint = () => {
      box.innerHTML = '<div class="label" style="margin-bottom:6px">不同意的话可以直接改：</div>' +
        '<div class="answer-list">' + p.options.map((o) =>
          '<label class="opt' + (picked.indexOf(o.key) >= 0 ? " on" : "") + '" data-cf-key="' + esc(o.key) + '">' +
          '<span class="mark ' + (p.widget === "multi" ? "square" : "round") + '">' +
          (p.widget === "multi" ? "✓" : "●") + "</span>" +
          '<span class="v"><span class="k">' + esc(o.key) + ".</span>" + esc(o.value) + "</span></label>").join("") +
        "</div>";
      $$("[data-cf-key]", box).forEach((node) => {
        node.onclick = () => {
          const k = node.dataset.cfKey;
          if (p.widget === "multi") {
            const i = picked.indexOf(k);
            if (i >= 0) picked.splice(i, 1); else picked.push(k);
            picked.sort();
          } else { picked.length = 0; picked.push(k); }
          paint();
        };
      });
    };
    paint();
    modal.__picked = picked;
  }

  let left = data.timeout;
  const tick = () => {
    const box = $("#cf-count");
    if (!box) return;
    box.className = "countdown" + (left <= 10 ? " urgent" : "");
    box.innerHTML = "<b>" + Math.max(0, left) + "</b> 秒后自动放弃提交";
    left -= 1;
    if (left < -1) clearInterval(confirmTimers[data.token]);
  };
  tick();
  confirmTimers[data.token] = setInterval(tick, 1000);
}

function closeConfirmModal(token) {
  clearInterval(confirmTimers[token]);
  delete confirmTimers[token];
  const found = modalStack.find((m) => {
    const modal = m.overlay.querySelector(".modal");
    return modal && modal.dataset.token === token;
  });
  if (found) closeModal(found.overlay);
}

async function decideConfirm(token, ok) {
  const found = modalStack.find((m) => {
    const modal = m.overlay.querySelector(".modal");
    return modal && modal.dataset.token === token;
  });
  const picked = found ? found.overlay.querySelector(".modal").__picked : null;
  closeConfirmModal(token);
  const res = await api.confirm_decide(token, ok, ok && picked ? picked : null);
  if (!res.ok && res.error) toastMsg(res.error, "error");
}

// ============================================================ 历史记录

async function renderHistory() {
  $("#main").innerHTML = '<div class="page"><div class="page-head"><h1 class="page-title">历史记录</h1>' +
    '<div class="page-sub">每节课的题目和答案都存在本地</div></div>' +
    '<div class="loading"><span class="spin"></span>正在读取……</div></div>';

  const res = await api.list_history();
  if (S.view !== "history") return;
  const items = (res.ok && res.items) || [];
  const page = $(".page");
  if (!page) return;

  if (!items.length) {
    page.innerHTML = '<div class="page-head"><h1 class="page-title">历史记录</h1></div>' +
      '<div class="empty"><svg viewBox="0 0 24 24"><path d="M12 7v5l3 2M3.5 12a8.5 8.5 0 1 0 2.5-6M3 4v4h4"/></svg>' +
      "<h3>还没有记录</h3><p>上过的课会自动存档，下课后可以回来复习题目、看 AI 讲解、导出课件</p></div>";
    return;
  }

  const groups = {};
  items.forEach((it) => {
    const key = fmtDate(it.startedAt);
    (groups[key] = groups[key] || []).push(it);
  });

  page.innerHTML = '<div class="page-head"><h1 class="page-title">历史记录</h1>' +
    '<div class="page-sub">共 ' + items.length + " 节课</div></div>" +
    Object.keys(groups).map((date) =>
      '<div class="hist-group"><div class="hist-date">' + esc(date) + "</div>" +
      groups[date].map(histRow).join("") + "</div>").join("");
}

function histRow(it) {
  const time = fmtTime(it.startedAt);
  const parts = [];
  if (time) parts.push(time);
  parts.push(it.problemCount + " 道题");
  parts.push("已提交 " + it.answered);
  if (it.slides) parts.push(it.slides + " 页课件");
  return (
    '<div class="hist-row card" data-act="open-history" data-id="' + esc(it.id) + '">' +
      '<div class="hist-main"><div class="hist-name">' + esc(it.lessonName) + "</div>" +
        '<div class="hist-sub">' + esc(parts.join(" · ")) + "</div></div>" +
      '<div class="hist-actions">' +
        '<button class="btn sm" data-act="open-history" data-id="' + esc(it.id) + '">' + icon("book") + "查看</button>" +
        '<button class="btn sm ghost danger-ghost" data-act="del-history" data-id="' + esc(it.id) + '" data-name="' +
          esc(it.lessonName) + '">' + icon("trash") + "</button>" +
      "</div>" +
    "</div>");
}

// ============================================================ 上手清单

function showOnboarding() {
  const st = S.state;
  const loginOk = st.login.state === "ok";
  const modes = (S.meta && S.meta.modes) || [];
  let mode = (st.mode && st.mode.key) || "ai_confirm";
  let auto = true;

  const modal = openModal(
    '<div class="modal-head"><h2 class="modal-title">几步就能用起来</h2><div class="spacer"></div>' +
      '<button class="x" data-act="skip-onboarding">' + icon("close") + "</button></div>" +
    '<div class="modal-body">' +
      '<div class="hint" style="margin-bottom:14px">做完前两步就能上课用，后面两步以后也能在设置里改。</div>' +
      '<div class="steps" id="ob-steps"></div>' +
    "</div>" +
    '<div class="modal-foot"><span class="hint" id="ob-hint"></span><div class="spacer"></div>' +
      '<button class="btn ghost" data-act="skip-onboarding">以后再说</button>' +
      '<button class="btn primary" data-act="finish-onboarding">开始使用</button></div>',
    { size: "md", sticky: true });

  modal.id = "onboarding";

  const paint = () => {
    const ok = S.state.login.state === "ok";
    const aiOk = S.state.ai.ready;
    $("#ob-steps").innerHTML =
      step(1, ok, "登录雨课堂", ok ? "已登录 · " + esc(S.state.login.name || "") : "扫码后才能签到、收题",
        ok ? "" : '<button class="btn sm primary" data-act="login">扫码登录</button>') +
      step(2, aiOk, "配置 AI", aiOk ? "已配置 · " + esc(S.state.ai.model) : "填好接口和 Key，AI 才能帮你解题",
        '<button class="btn sm" data-act="settings-ai">' + (aiOk ? "修改" : "去配置") + "</button>") +
      '<div class="step"><div class="step-n">3</div><div class="step-main">' +
        '<div class="step-t">推题时怎么处理</div>' +
        '<div class="radios" style="margin-top:10px">' + modes.map((m) =>
          '<label class="radio-card' + (mode === m.key ? " on" : "") + '" data-ob-mode="' + esc(m.key) + '">' +
          '<span class="mark"></span><span><span class="t">' + esc(m.label) +
          (m.key === "ai_confirm" ? '<span class="tag-rec">推荐</span>' : "") + "</span>" +
          '<span class="d">' + esc(m.desc) + "</span></span></label>").join("") + "</div>" +
      "</div></div>" +
      '<div class="step"><div class="step-n">4</div><div class="step-main">' +
        '<label class="toggle"><input type="checkbox" id="ob-auto"' + (auto ? " checked" : "") + ">" +
        '<span class="switch"></span><span><span class="t">打开程序就自动开始监听</span>' +
        '<span class="d">省得每次上课前还要手动点一下</span></span></label></div></div>';

    $$("[data-ob-mode]").forEach((node) => {
      node.onclick = () => { mode = node.dataset.obMode; paint(); };
    });
    const chk = $("#ob-auto");
    if (chk) chk.onchange = () => { auto = chk.checked; };
    $("#ob-hint").textContent = ok && aiOk ? "都准备好了" :
      "还差：" + [!ok && "登录", !aiOk && "配置 AI"].filter(Boolean).join("、");
  };

  function step(n, done, title, desc, action) {
    return '<div class="step' + (done ? " done" : "") + '"><div class="step-n">' + (done ? "✓" : n) + "</div>" +
      '<div class="step-main"><div class="step-t">' + esc(title) + "</div>" +
      '<div class="step-d">' + desc + "</div></div>" +
      '<div class="step-act">' + (action || "") + "</div></div>";
  }

  paint();
  modal.__repaint = paint;
  modal.__finish = async () => {
    await api.set_onboarded({ mode, auto_monitor: auto });
    closeModal();
    const st2 = S.state;
    if (st2.login.state === "ok" && !st2.monitor.active && !st2.testMode) api.start_monitor();
  };
}

// ============================================================ 设置

let draft = null;      // 正在编辑的设置副本
let saved = null;      // 上次保存的快照，用于判断有没有改动

async function renderSettings(anchor) {
  $("#main").innerHTML = '<div class="page"><div class="page-head"><h1 class="page-title">设置</h1></div>' +
    '<div class="loading"><span class="spin"></span>正在读取……</div></div>';
  const res = await api.get_settings();
  if (S.view !== "settings") return;
  if (!res.ok) { toastMsg(res.error || "读取设置失败", "error"); return; }
  draft = res.settings;
  saved = JSON.stringify(draft);
  paintSettings();
  if (anchor) {
    const node = document.getElementById("set-" + anchor);
    if (node) node.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function paintSettings() {
  const meta = S.meta || { providers: [], efforts: [], modes: [], notifyKinds: [] };
  const ai = draft.ai_config || {};
  const provider = meta.providers.find((p) => p.key === ai.provider) || meta.providers[0] || {};
  const notify = draft.notify_config || {};
  const answer = draft.answer_config || {};
  const mode = answer.mode || "saved";

  $("#main").innerHTML = '<div class="page">' +
    '<div class="page-head"><h1 class="page-title">设置</h1></div>' +
    '<div class="settings">' +
      '<nav class="settings-nav">' +
        '<a href="#set-account">账号</a><a href="#set-answer">答题方式</a><a href="#set-ai">AI 服务</a>' +
        '<a href="#set-notify">提醒与启动</a><a href="#set-misc">弹幕与外观</a>' +
      "</nav>" +
      "<div>" +
        accountCard() +
        answerCard(meta, mode, answer) +
        aiCard(meta, ai, provider) +
        notifyCard(meta, notify) +
        miscCard() +
        '<div class="save-bar" id="save-bar">' +
          '<span id="save-text">有未保存的改动</span><div class="spacer"></div>' +
          '<button class="btn ghost sm" data-act="reset-settings">放弃</button>' +
          '<button class="btn primary sm" data-act="save-settings">保存</button></div>' +
      "</div>" +
    "</div></div>";
  bindSettings();
  updateSaveBar();
}

function accountCard() {
  const st = S.state;
  const ok = st.login.state === "ok";
  const ui = LOGIN_UI[st.login.state] || LOGIN_UI.checking;
  const who = ok ? (st.login.name || "已登录") : ui.who;
  return '<div class="card set-card" id="set-account"><h3>账号</h3>' +
    '<div class="hint">登录状态只保存在本机，退出后会清除。</div>' +
    '<div class="input-row" style="margin-top:4px">' +
      '<span class="dot" style="width:9px;height:9px;border-radius:50%;background:' + ui.color + '"></span>' +
      '<span style="font-weight:650">' + esc(who) + "</span>" +
      '<span class="hint">' + esc(ok ? "雨课堂账号正常" : ui.sub) + "</span>" +
      '<div class="spacer"></div>' +
      (ok ? '<button class="btn sm" data-act="switch-account">换个账号登录</button>' +
            '<button class="btn sm ghost danger-ghost" data-act="logout">退出登录</button>'
          : '<button class="btn sm primary" data-act="login">扫码登录</button>') +
    "</div></div>";
}

function answerCard(meta, mode, answer) {
  const delay = (answer.answer_delay || {});
  const custom = ((delay.custom || {}).time) || 0;
  return '<div class="card set-card" id="set-answer"><h3>课上推送新题目时</h3>' +
    '<div class="hint">越往下越自动，人工核对的机会也越少。</div>' +
    '<div class="radios">' + meta.modes.map((m) =>
      '<label class="radio-card' + (mode === m.key ? " on" : "") + '" data-set-mode="' + esc(m.key) + '">' +
      '<span class="mark"></span><span><span class="t">' + esc(m.label) +
      (m.key === "ai_confirm" ? '<span class="tag-rec">推荐</span>' : "") + "</span>" +
      '<span class="d">' + esc(m.desc) + "</span></span></label>").join("") + "</div>" +
    '<div class="indent' + (mode === "ai_confirm" ? "" : " dim") + '" style="margin-top:10px">' +
      '<div class="input-row"><span class="hint">确认框等待</span>' +
      '<input class="input" type="number" min="5" max="300" style="width:90px" data-set="answer_config.confirm_timeout" value="' +
        (answer.confirm_timeout || 60) + '"><span class="hint">秒，超时不点就不提交</span></div></div>' +
    '<hr class="set-sep">' +
    '<div class="label">提交延迟</div><div class="hint" style="margin-bottom:8px">避免秒答，看起来更自然。</div>' +
    '<div class="radios two">' +
      radioSmall("answer_config.answer_delay.type", 1, delay.type === 1 || !delay.type, "随机延迟", "推荐") +
      radioSmall("answer_config.answer_delay.type", 2, delay.type === 2, "固定延迟", "") + "</div>" +
    '<div class="indent' + (delay.type === 2 ? "" : " dim") + '" style="margin-top:10px">' +
      '<div class="input-row"><span class="hint">延迟</span>' +
      '<input class="input" type="number" min="0" max="300" style="width:90px" data-set="answer_config.answer_delay.custom.time" value="' +
      custom + '"><span class="hint">秒</span></div></div></div>';
}

function radioSmall(path, value, on, title, tag) {
  return '<label class="radio-card' + (on ? " on" : "") + '" data-set-radio="' + esc(path) +
    '" data-value="' + esc(value) + '"><span class="mark"></span><span><span class="t">' + esc(title) +
    (tag ? '<span class="tag-rec">' + esc(tag) + "</span>" : "") + "</span></span></label>";
}

function aiCard(meta, ai, provider) {
  return '<div class="card set-card" id="set-ai"><h3>AI 服务</h3>' +
    '<div class="hint">地址和模型不会预填，需要你自己填——预置一个陌生网关等于把你的 Key 默认发给第三方。</div>' +
    '<div class="field"><label>接口格式</label>' +
      '<select class="select" data-set="ai_config.provider">' + meta.providers.map((p) =>
        '<option value="' + esc(p.key) + '"' + (p.key === ai.provider ? " selected" : "") + ">" +
        esc(p.label) + "</option>").join("") + "</select>" +
      '<div class="hint">' + (provider.path ? "请求地址 = 接口地址 + " + esc(provider.path) : "使用官方 SDK，不需要填地址") + "</div></div>" +
    '<div class="field"><label>API Key</label>' +
      '<div class="input-row"><input class="input" type="password" data-set="ai_config.api_key" value="' +
        esc(ai.api_key || "") + '" placeholder="粘贴你的 API Key">' +
      '<button class="btn" data-act="toggle-key">显示</button></div></div>' +
    (provider.needsUrl !== false ?
      '<div class="field"><label>接口地址</label>' +
        '<input class="input" data-set="ai_config.base_url" value="' + esc(ai.base_url || "") +
        '" placeholder="' + esc(provider.urlExample || "") + '">' +
        '<div class="hint">只填到域名，路径会自动补全</div></div>' : "") +
    '<div class="field"><label>模型</label>' +
      '<div class="input-row"><input class="input" list="model-list" data-set="ai_config.model" value="' +
        esc(ai.model || "") + '" placeholder="' + esc(provider.modelExample || "") + '">' +
      '<button class="btn" data-act="fetch-models">获取列表</button></div>' +
      '<datalist id="model-list"></datalist><div class="result" id="model-result"></div></div>' +
    '<div class="field"><label>思考强度</label>' +
      '<select class="select" data-set="ai_config.thinking_effort">' + meta.efforts.map((e) =>
        '<option value="' + esc(e.key) + '"' + (e.key === ai.thinking_effort ? " selected" : "") + ">" +
        esc(e.label) + "</option>").join("") + "</select>" +
      '<div class="hint">高档位更准也更慢。能不能用取决于模型，用不了会有提示。</div></div>' +
    '<div class="field"><label>批量解题并发数</label>' +
      '<input class="input" type="number" min="1" max="8" style="width:90px" data-set="ai_config.concurrency" value="' +
      (ai.concurrency || 3) + '"><div class="hint">太高容易被限流</div></div>' +
    '<div class="input-row"><button class="btn" data-act="test-ai">测试连接</button>' +
      '<span class="result" id="ai-result"></span></div></div>';
}

function notifyCard(meta, notify) {
  const on = notify.enabled !== false;
  const ways = [["system", "系统通知"], ["sound", "提示音"], ["toast", "屏幕角落浮窗"]];
  return '<div class="card set-card" id="set-notify"><h3>提醒与启动</h3>' +
    '<div class="hint">上课时不用一直盯着窗口，有事会叫你。</div>' +
    '<label class="toggle"><input type="checkbox" data-set="auto_monitor"' +
      (draft.auto_monitor ? " checked" : "") + '><span class="switch"></span>' +
      '<span><span class="t">打开程序就自动开始监听</span>' +
      '<span class="d">确认登录有效后才会开始</span></span></label>' +
    '<hr class="set-sep">' +
    '<label class="toggle"><input type="checkbox" data-set="notify_config.enabled"' +
      (on ? " checked" : "") + '><span class="switch"></span>' +
      '<span><span class="t">开启提醒</span></span></label>' +
    '<div class="indent' + (on ? "" : " dim") + '">' +
      '<div class="label" style="margin:10px 0 6px">什么时候提醒</div><div class="toggles">' +
      meta.notifyKinds.map((k) =>
        '<label class="toggle"><input type="checkbox" data-set="notify_config.' + esc(k.key) + '"' +
        (notify[k.key] !== false ? " checked" : "") + '><span class="switch"></span>' +
        '<span><span class="t">' + esc(k.label) +
        (k.key === "callme" ? '</span><span class="d">紧急：连响三声并把窗口拉到最前</span>' : "</span>") +
        "</span></label>").join("") + "</div>" +
      '<div class="label" style="margin:14px 0 6px">用什么方式</div><div class="toggles">' +
      ways.map(([k, label]) =>
        '<label class="toggle"><input type="checkbox" data-set="notify_config.' + k + '"' +
        (notify[k] !== false ? " checked" : "") + '><span class="switch"></span>' +
        '<span><span class="t">' + label + "</span></span></label>").join("") + "</div>" +
      '<div class="input-row" style="margin-top:14px"><button class="btn sm" data-act="test-notify">' +
      icon("bell") + "试一下</button><span class=\"hint\">按当前勾选发一条，不用先保存</span></div></div></div>";
}

function miscCard() {
  const danmu = draft.danmu_config || {};
  const themes = [["auto", "跟随系统"], ["light", "浅色"], ["dark", "深色"]];
  return '<div class="card set-card" id="set-misc"><h3>弹幕与外观</h3>' +
    '<label class="toggle"><input type="checkbox" data-set="auto_danmu"' +
      (draft.auto_danmu ? " checked" : "") + '><span class="switch"></span>' +
      '<span><span class="t">自动跟发弹幕</span>' +
      '<span class="d">同一条弹幕被足够多人发过之后，也跟着发一条</span></span></label>' +
    '<div class="indent' + (draft.auto_danmu ? "" : " dim") + '" style="margin-top:8px">' +
      '<div class="input-row"><span class="hint">达到</span>' +
      '<input class="input" type="number" min="1" max="100" style="width:90px" data-set="danmu_config.danmu_limit" value="' +
      (danmu.danmu_limit || 5) + '"><span class="hint">人时跟发</span></div></div>' +
    '<hr class="set-sep">' +
    '<div class="field"><label>外观</label><div class="radios two">' +
      themes.map(([k, label]) => radioSmall("ui_theme", k, draft.ui_theme === k, label, "")).join("") +
    "</div></div>" +
    '<hr class="set-sep">' +
    '<div class="input-row"><button class="btn sm" data-act="open-config-dir">' + icon("folder") +
      "打开数据目录</button><span class=\"hint\">配置、课件截图、历史记录都在这里</span></div>" +
    '<div class="input-row" style="margin-top:10px"><button class="btn sm" data-act="show-onboarding">' +
      "再看一次上手清单</button></div></div>";
}

function getPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
}

function setPath(obj, path, value) {
  const keys = path.split(".");
  const last = keys.pop();
  const target = keys.reduce((o, k) => (o[k] = o[k] || {}), obj);
  target[last] = value;
}

function bindSettings() {
  $$("[data-set]").forEach((node) => {
    const path = node.dataset.set;
    const handler = () => {
      let value;
      if (node.type === "checkbox") value = node.checked;
      else if (node.type === "number") value = Number(node.value) || 0;
      else value = node.value;
      setPath(draft, path, value);
      // 主题、接口格式、开关这些会改变界面结构，需要重画
      if (["ui_theme", "ai_config.provider", "notify_config.enabled", "auto_danmu"].includes(path)) {
        if (path === "ui_theme") applyTheme(value);
        paintSettings();
      } else {
        updateSaveBar();
      }
    };
    node.addEventListener(node.tagName === "SELECT" || node.type === "checkbox" ? "change" : "input", handler);
  });

  $$("[data-set-radio]").forEach((node) => {
    node.onclick = () => {
      const raw = node.dataset.value;
      const value = /^\d+$/.test(raw) ? Number(raw) : raw;
      setPath(draft, node.dataset.setRadio, value);
      if (node.dataset.setRadio === "ui_theme") applyTheme(value);
      paintSettings();
    };
  });

  $$("[data-set-mode]").forEach((node) => {
    node.onclick = () => { setPath(draft, "answer_config.mode", node.dataset.setMode); paintSettings(); };
  });

  $$(".settings-nav a").forEach((a) => {
    a.onclick = (e) => {
      e.preventDefault();
      const node = document.querySelector(a.getAttribute("href"));
      if (node) node.scrollIntoView({ behavior: "smooth", block: "start" });
      $$(".settings-nav a").forEach((x) => x.classList.toggle("active", x === a));
    };
  });
}

function updateSaveBar() {
  const bar = $("#save-bar");
  if (bar) bar.classList.toggle("show", JSON.stringify(draft) !== saved);
}

function applyTheme(theme) {
  const dark = theme === "dark" ||
    (theme !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

// ============================================================ 动作分发

const ACTIONS = {
  nav: (t) => switchView(t.dataset.view),
  "close-modal": () => closeModal(),
  "clear-log": () => { S.logs = []; renderLog(); },

  account: () => {
    const st = S.state;
    if (st && st.login.state === "ok") switchView("settings", "account");
    else openLoginModal();
  },
  logout: async () => {
    if (!confirm("退出登录？\n会停止监听并清除本机保存的登录状态，答题记录和设置都保留。")) return;
    const res = await api.logout();
    if (!res.ok) return toastMsg(res.error || "退出失败", "error");
    toastMsg("已退出登录");
    if (S.view === "settings") renderSettings("account");
  },
  "switch-account": async () => {
    // 先退掉当前账号，再拉起扫码；否则扫的还是同一个人
    const res = await api.logout();
    if (!res.ok) return toastMsg(res.error || "切换失败", "error");
    openLoginModal();
  },
  login: () => openLoginModal(),
  "close-login": () => { if (loginOverlay) closeModal(loginOverlay); },
  "login-refresh": () => api.login_refresh(),

  "toggle-monitor": async () => {
    const st = S.state;
    const res = st.monitor.active ? await api.stop_monitor() : await api.start_monitor();
    if (!res.ok && res.error) {
      toastMsg(res.error, "error");
      if (res.error.indexOf("登录") >= 0) openLoginModal();
    }
  },
  "test-mode-on": async () => {
    const res = await api.enter_test_mode();
    if (!res.ok) toastMsg(res.error, "error");
  },

  "open-lesson": (t) => openLessonView(t.dataset.id),
  "open-problem": (t) => openProblemView(t.dataset.id),
  filter: (t) => { S.filter = t.dataset.k; refreshLessonModal(); },

  "solve-all": async () => {
    const res = await api.solve_all(S.openLesson.id);
    if (!res.ok) toastMsg(res.error, "error");
  },
  "cancel-solve-all": () => api.cancel_solve_all(S.openLesson.id),

  pick: (t) => pickOption(t.dataset.key),

  "save-answer": () => busy('[data-act="save-answer"]', async () => {
    const d = answerDraft;
    const res = await api.save_answer(d.lessonId, d.problem.id, d.answers);
    if (!res.ok) return setStatus(res.error, "error");
    setStatus("已保存到本地，课上推送这道题时会自动提交", "ok");
    refreshLessonModal();
  }),

  "submit-answer": () => busy('[data-act="submit-answer"]', async () => {
    const d = answerDraft;
    if (!d.answers.length) return setStatus("还没有填写答案", "error");
    if (!confirm("确定把答案「" + d.answers.join("、") + "」提交到雨课堂吗？\n提交后不能修改。")) return;
    const res = await api.submit_answer(d.lessonId, d.problem.id, d.answers);
    if (!res.ok) return setStatus(res.error, "error");
    setStatus("提交成功", "ok");
    d.problem = res.problem;
    renderAnswerArea();
    refreshLessonModal();
    setTimeout(() => closeModal(), 700);
  }),

  "ai-solve": () => busy('[data-act="ai-solve"]', async () => {
    setStatus("AI 正在作答……");
    const d = answerDraft;
    const res = await api.ai_solve(d.lessonId, d.problem.id);
    if (!res.ok) return setStatus(res.error, "error");
    d.answers = res.answers.slice();
    d.problem = res.problem;
    renderAnswerArea();
    setStatus("AI 答案：" + res.answers.join("、") + " —— 核对后点保存或提交", "ok");
    refreshLessonModal();
  }),

  "ai-explain": () => busy('[data-act="ai-explain"]', async () => {
    setStatus("AI 正在讲解……");
    const d = answerDraft;
    const res = await api.ai_explain(d.lessonId, d.problem.id);
    if (!res.ok) return setStatus(res.error, "error");
    d.problem = res.problem;
    if (!d.answers.length && res.answer.length) { d.answers = res.answer.slice(); renderAnswerArea(); }
    renderNotes(res.problem);
    setStatus("讲解已生成", "ok");
    refreshLessonModal();
  }),

  "ai-review": () => busy('[data-act="ai-review"]', async () => {
    const d = answerDraft;
    if (!d.answers.length) return setStatus("先填个答案再复核", "error");
    setStatus("AI 正在复核……");
    const res = await api.ai_review(d.lessonId, d.problem.id, d.answers);
    if (!res.ok) return setStatus(res.error, "error");
    d.problem = res.problem;
    renderNotes(res.problem);
    setStatus(res.agreed ? "复核通过" : "复核建议改成：" + (res.answer || []).join("、"),
      res.agreed ? "ok" : "error");
    refreshLessonModal();
  }),

  "confirm-yes": (t) => decideConfirm(t.dataset.token, true),
  "confirm-no": (t) => decideConfirm(t.dataset.token, false),

  "export-pdf": (t) => busy(null, async () => {
    const res = await api.export_pdf(t.dataset.id);
    if (res.cancelled) return;
    if (!res.ok) return toastMsg(res.error, "error");
    showToast({ title: "已导出课件 PDF", message: res.pages + " 页 · 点这里在访达中打开", urgent: false });
    const box = $("#toasts").lastElementChild;
    if (box) box.onclick = () => { dismiss(box); api.reveal(res.path); };
  }),

  "open-history": (t) => openLessonView("h:" + t.dataset.id),
  "del-history": async (t) => {
    if (!confirm("删除「" + t.dataset.name + "」的记录？\n只删本地存档，不影响雨课堂。")) return;
    await api.delete_history(t.dataset.id);
    renderHistory();
  },

  "settings-ai": () => switchView("settings", "ai"),
  "settings-answer": () => switchView("settings", "answer"),
  "save-settings": () => busy('[data-act="save-settings"]', async () => {
    const res = await api.save_settings(draft);
    if (!res.ok) return toastMsg(res.error || "保存失败", "error");
    draft = res.settings;
    saved = JSON.stringify(draft);
    paintSettings();
    toastMsg("设置已保存");
  }),
  "reset-settings": () => { draft = JSON.parse(saved); applyTheme(draft.ui_theme); paintSettings(); },
  "toggle-key": (t) => {
    const input = t.parentElement.querySelector("input");
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    t.textContent = show ? "隐藏" : "显示";
  },
  "test-ai": () => busy('[data-act="test-ai"]', async () => {
    const box = $("#ai-result");
    box.className = "result"; box.textContent = "正在测试……";
    const res = await api.test_ai(draft.ai_config);
    box.className = "result " + (res.ok ? "ok" : "err");
    box.textContent = (res.ok ? "✓ " : "✗ ") + (res.message || res.error);
  }),
  "fetch-models": () => busy('[data-act="fetch-models"]', async () => {
    const box = $("#model-result");
    box.className = "result"; box.textContent = "正在获取……";
    const res = await api.list_models(draft.ai_config);
    if (!res.ok) { box.className = "result err"; box.textContent = "✗ " + res.error; return; }
    $("#model-list").innerHTML = res.models.map((m) => '<option value="' + esc(m) + '">').join("");
    box.className = "result ok";
    box.textContent = "✓ 共 " + res.models.length + " 个模型，点输入框可选";
  }),
  "test-notify": () => api.test_notify(draft.notify_config),
  "open-config-dir": () => api.open_config_dir(),
  "show-onboarding": () => showOnboarding(),
  "skip-onboarding": async () => { await api.set_onboarded({}); closeModal(); },
  "finish-onboarding": () => {
    const modal = $("#onboarding");
    if (modal && modal.__finish) modal.__finish();
  },
};

document.addEventListener("click", (e) => {
  const target = e.target.closest("[data-act]");
  if (!target) return;
  const fn = ACTIONS[target.dataset.act];
  if (!fn) return;
  e.preventDefault();
  e.stopPropagation();
  fn(target);
});

$("#test-toggle").addEventListener("change", async (e) => {
  const res = e.target.checked ? await api.enter_test_mode() : await api.exit_test_mode();
  if (!res.ok) { toastMsg(res.error, "error"); e.target.checked = !e.target.checked; }
});

// ============================================================ 视图切换与启动

function switchView(view, anchor) {
  S.view = view;
  renderShell();
  if (view === "home") renderHome();
  else if (view === "history") renderHistory();
  else if (view === "settings") renderSettings(anchor);
}

async function boot() {
  const res = await api.ready();
  if (!res || res.ok === false) {
    $("#main").innerHTML = '<div class="page"><div class="empty"><h3>启动失败</h3><p>' +
      esc((res && res.error) || "无法连接到程序内核") + "</p></div></div>";
    return;
  }
  S.state = res.state;
  S.lessons = res.lessons || [];
  S.logs = res.logs || [];
  S.meta = res.meta;
  S.ready = true;
  applyTheme(S.state.theme);
  switchView("home");
  if (!S.state.onboarded) setTimeout(showOnboarding, 400);
}

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (S.state && S.state.theme === "auto") applyTheme("auto");
});

if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener("pywebviewready", boot);
