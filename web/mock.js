/* 浏览器里预览界面用的假数据：index.html?mock。不参与打包运行。 */
(function () {
  const img = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400">' +
    '<rect width="640" height="400" fill="#fff"/><rect width="640" height="52" fill="#7A1F8C"/>' +
    '<text x="20" y="34" fill="#fff" font-size="18" font-family="sans-serif">Sample slide</text>' +
    '<text x="24" y="100" font-size="17" font-family="sans-serif">下列哪一项是 Python 中定义函数的关键字?</text>' +
    ["func", "def", "function", "lambda"].map((v, i) =>
      '<circle cx="36" cy="' + (140 + i * 46) + '" r="10" fill="none" stroke="#7A1F8C" stroke-width="2"/>' +
      '<text x="58" y="' + (146 + i * 46) + '" font-size="15" font-family="sans-serif">' +
      "ABCD"[i] + ". " + v + "</text>").join("") + "</svg>")));

  const problems = [
    { id: "1", page: 1, type: "单选题", widget: "single", body: "下列哪一项是 Python 中用于定义函数的关键字？",
      options: [["A", "func"], ["B", "def"], ["C", "function"], ["D", "lambda"]].map(([key, value]) => ({ key, value })),
      blanks: 1, answers: ["B"], answerText: "B", submitted: false, explanation: "", review: null, hasImage: true },
    { id: "2", page: 2, type: "多选题", widget: "multi", body: "以下哪些属于 Python 的内置数据类型？（多选）",
      options: [["A", "list"], ["B", "dict"], ["C", "vector"], ["D", "tuple"]].map(([key, value]) => ({ key, value })),
      blanks: 1, answers: [], answerText: "", submitted: false, explanation: "", review: null, hasImage: true },
    { id: "3", page: 3, type: "填空题", widget: "blanks", body: "填空：HTTP 状态码 ____ 表示未找到资源，____ 表示服务器内部错误。",
      options: [], blanks: 2, answers: ["404", "500"], answerText: "404、500", submitted: false,
      explanation: "404 Not Found 表示服务器找不到请求的资源；500 Internal Server Error 表示服务端自身出错。",
      review: { ok: true, answer: ["404", "500"], reason: "" }, hasImage: true },
    { id: "4", page: 4, type: "主观题", widget: "text", body: "请简述你对课堂互动工具的看法。",
      options: [], blanks: 1, answers: [], answerText: "", submitted: false, explanation: "", review: null, hasImage: true },
    { id: "5", page: 5, type: "单选题", widget: "single", body: "这道题演示已提交状态，界面上会被锁定。",
      options: [["A", "可以改"], ["B", "不能改"]].map(([key, value]) => ({ key, value })),
      blanks: 1, answers: ["B"], answerText: "B", submitted: true, explanation: "", review: null, hasImage: true },
  ];

  const state = {
    version: "2.0.0",
    login: { state: "ok", name: "唐琦" },
    monitor: { active: true, text: "在上课程 2 门", lastCheck: "10:24:31" },
    testMode: false,
    ai: { ready: true, provider: "Anthropic 格式", model: "glm-5.3-flash", effort: "medium" },
    mode: { key: "ai_confirm", label: "AI 解答，问过我再交" },
    onboarded: true, theme: "auto",
  };

  const lessons = [
    { id: "L1", name: "组合数学", status: "live", statusText: "监听中", problemCount: 5, submitted: 1, ready: 2, empty: 2, slides: 32 },
    { id: "L2", name: "数据结构与算法", status: "live", statusText: "监听中", problemCount: 3, submitted: 3, ready: 0, empty: 0, slides: 18 },
    { id: "L3", name: "马克思主义基本原理", status: "finished", statusText: "已下课", problemCount: 8, submitted: 8, ready: 0, empty: 0, slides: 45 },
  ];

  const logs = [
    { t: "10:02:11", level: "info", text: "程序已启动（v2.0.0）" },
    { t: "10:02:12", level: "info", text: "监听已启动，每 5 秒检查一次正在上课的课程" },
    { t: "10:05:40", level: "lesson", text: "检测到课程 组合数学 正在上课，已加入监听" },
    { t: "10:05:43", level: "info", text: "组合数学 签到成功" },
    { t: "10:05:47", level: "info", text: "组合数学 已加载 5 道题目" },
    { t: "10:18:02", level: "lesson", text: "组合数学 推送了新题目（第1页），剩余 60 秒" },
    { t: "10:18:05", level: "info", text: "组合数学 第1页 AI 给出答案：B" },
    { t: "10:18:21", level: "info", text: "组合数学 自动回答成功" },
    { t: "10:22:14", level: "callme", text: "组合数学 点名了，点到了：唐琦" },
    { t: "10:24:02", level: "warn", text: "数据结构与算法 第2页还没有保存答案，剩余 45 秒" },
    { t: "10:24:31", level: "error", text: "第7页截图下载失败（HTTP 404）" },
  ];

  const meta = {
    providers: [
      { key: "anthropic", label: "Anthropic 格式（Claude / GLM / 兼容网关）", path: "/v1/messages", needsUrl: true, urlExample: "https://api.anthropic.com", modelExample: "claude-sonnet-5 / glm-5.3-flash", reasoning: "anthropic" },
      { key: "openai_responses", label: "OpenAI Responses 格式（Codex）", path: "/v1/responses", needsUrl: true, urlExample: "https://api.openai.com", modelExample: "gpt-5.1-codex", reasoning: "effort" },
      { key: "openai_chat", label: "OpenAI Chat Completions 格式", path: "/v1/chat/completions", needsUrl: true, urlExample: "https://api.openai.com", modelExample: "gpt-4o", reasoning: "effort" },
      { key: "qwen", label: "通义千问 Qwen（dashscope SDK）", path: "", needsUrl: false, urlExample: "", modelExample: "qwen-vl-max-latest", reasoning: "none" },
    ],
    efforts: [["off", "关闭"], ["minimal", "最低"], ["low", "低"], ["medium", "中"], ["high", "高"], ["xhigh", "极高"], ["max", "最高"]].map(([key, label]) => ({ key, label })),
    modes: [
      { key: "notify", label: "只提示我", desc: "只在动态里提醒你有新题，全部自己作答" },
      { key: "saved", label: "只交已保存的答案", desc: "提前填好的答案会自动提交；没答案的题只提醒" },
      { key: "ai_confirm", label: "AI 解答，问过我再交", desc: "AI 答完弹窗给你过目，同意才提交" },
      { key: "ai_auto", label: "AI 解答并直接交", desc: "全自动，来不及人工核对" },
    ],
    notifyKinds: [["problem", "老师推送新题目"], ["callme", "点名点到我"], ["confirm", "AI 答完等我确认"],
      ["lesson", "上课签到 / 下课"], ["login", "登录失效"]].map(([key, label]) => ({ key, label })),
    configDir: "/Users/you/Library/RainClassroomAssistant", version: "2.0.0",
  };

  const settings = {
    ui_theme: "auto", auto_danmu: true, danmu_config: { danmu_limit: 5 }, auto_monitor: true, onboarded: true,
    answer_config: { mode: "ai_confirm", confirm_timeout: 60, answer_delay: { type: 1, custom: { time: 0 } } },
    ai_config: { provider: "anthropic", api_key: "sk-demo-key", base_url: "https://api.anthropic.com",
      model: "glm-5.3-flash", thinking_effort: "medium", concurrency: 3 },
    notify_config: { enabled: true, sound: true, system: true, toast: true,
      problem: true, callme: true, confirm: true, lesson: true, login: true },
  };

  const history = [
    { id: "h1", lessonName: "组合数学", startedAt: new Date().toISOString(), problemCount: 5, answered: 5, slides: 32 },
    { id: "h2", lessonName: "数据结构与算法", startedAt: new Date(Date.now() - 86400000).toISOString(), problemCount: 3, answered: 3, slides: 18 },
    { id: "h3", lessonName: "大学物理", startedAt: new Date(Date.now() - 3 * 86400000).toISOString(), problemCount: 6, answered: 4, slides: 27 },
  ];

  const ok = (extra) => Promise.resolve(Object.assign({ ok: true }, extra));
  window.pywebview = {
    api: {
      ready: () => ok({ state, lessons, logs, meta }),
      lesson_detail: (id) => ok({ id, name: lessons.find((l) => l.id === id) ? lessons.find((l) => l.id === id).name : "组合数学",
        readonly: String(id).startsWith("h:"), finished: false, test: false, slides: 32, problems, batch: false }),
      problem_image: () => ok({ image: img }),
      get_settings: () => ok({ settings: JSON.parse(JSON.stringify(settings)) }),
      save_settings: (s) => ok({ settings: s }),
      list_history: () => ok({ items: history }),
      list_models: () => ok({ models: ["glm-5.3-flash", "glm-5.3", "claude-opus-5", "gpt-5.6-sol"] }),
      test_ai: () => ok({ message: "连接成功，模型 glm-5.3-flash 可用" }),
      save_answer: () => ok({ problem: problems[0] }),
      submit_answer: () => ok({ problem: Object.assign({}, problems[0], { submitted: true }) }),
      ai_solve: () => ok({ answers: ["B"], problem: problems[0] }),
      ai_explain: () => ok({ answer: ["B"], explanation: "考点是函数定义语法。Python 用 def 关键字定义函数，func 和 function 不是关键字，lambda 只能定义匿名函数。",
        problem: Object.assign({}, problems[0], { explanation: "考点是函数定义语法。Python 用 def 关键字定义函数。" }) }),
      ai_review: () => ok({ agreed: true, answer: ["B"], reason: "", problem: problems[0] }),
      solve_all: () => ok({ total: 2 }),
      start_monitor: () => ok(), stop_monitor: () => ok(),
      enter_test_mode: () => ok({ lessonId: "L1" }), exit_test_mode: () => ok(),
      login_start: () => ok(), login_refresh: () => ok(), login_cancel: () => ok(),
      set_onboarded: () => ok({ settings }), test_notify: () => ok(),
      delete_history: () => ok(), export_pdf: () => ok({ pages: 32, path: "/tmp/x.pdf" }),
      cancel_solve_all: () => ok(), confirm_decide: () => ok(), open_config_dir: () => ok(), reveal: () => ok(),
    },
  };
  if (typeof boot === "function") boot();
})();
