# 测试

## Python 离线回归

全部不联网、不需要账号：

```bash
for t in tests/test_*.py; do python "$t" || break; done
```

| 文件 | 覆盖内容 |
| --- | --- |
| `test_app.py` | 控制器的每个对外接口：状态、课程、题目、作答、批量解题、确认流程、历史、导出、设置 |
| `test_protocol.py` | 用合成的雨课堂报文验证签到、收题去重、自动答题、题目锁定、下课 |
| `test_answer_mode.py` | 四种答题方式的行为差异，重点是「不该提交时绝不提交」 |
| `test_ai.py` / `test_providers.py` | 四种接口格式的请求体与返回解析、思考强度、错误提示 |
| `test_legacy_gateway.py` | 老网关只认废弃写法时的自动回退 |
| `test_timeout.py` | 超时真的可控，含服务端滴水式挂起的回归用例 |
| `test_notify.py` | 提醒开关、紧急提醒的特殊待遇、课堂事件触发 |

## 界面自检

界面问题（图标被撑大、元素溢出、文字被裁）Python 测试看不见，用 `web/audit.js`：

```bash
python -m http.server 8765 --directory web
```

浏览器打开 `http://127.0.0.1:8765/index.html?mock`，控制台执行：

```js
const s = document.createElement('script'); s.src = 'audit.js';
document.body.appendChild(s);
s.onload = async () => console.table((await runAudit()).problems);
```

它会依次走过 28 个界面状态（课堂的各种空/满状态、题目列表的每种筛选、四种题型的答题界面、
设置的每个分区、历史、上手清单、确认弹窗、扫码登录、浮窗提醒），检查：

- 按钮里的图标是否被撑大
- 元素是否超出视口
- 单行文字是否被裁且没有省略号
- 内容是否溢出容器

改完样式后建议在 820 / 900 / 1180 / 1400 几个宽度各跑一遍。
