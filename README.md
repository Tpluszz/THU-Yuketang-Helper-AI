# 清华大学荷塘雨课堂助手 - AI 版

基于 *TrickyDeath* 的 [RainClassroomAssistant](https://github.com/TrickyDeath/RainClassroomAssitant)，
经 [THU-Yuketang-Helper](https://github.com/zhangchi2004/THU-Yuketang-Helper) 适配清华荷塘雨课堂。

## 功能

- **自动签到**：检测到上课后自动签到并开始监听
- **四种答题方式**：从「只提示我」到「AI 解答并直接提交」，自己选替你做到哪一步
- **AI 解题**：支持 Anthropic、OpenAI Responses（Codex）、OpenAI Chat、通义千问四种接口格式；
  可批量解答整门课，也能单题解答、讲解思路、复核答案
- **不用盯着屏幕**：系统通知 + 提示音 + 屏幕角落浮窗；点名点到你会连响三声并把窗口拉到最前
- **课后复习**：每节课的题目、答案、AI 讲解自动存档，可回看；课件截图一键导出 PDF
- **多课程并行**：同时有多门课在上也能一起监听

## 安装与运行

```bash
pip install -r requirements.txt
python main.py
```

首次打开会有上手清单引导你走完「登录 → 配置 AI → 选答题方式」。

界面是本地 HTML，跑在系统自带的浏览器内核里（macOS 用 WebKit，Windows 用 WebView2），
不需要装 Chrome，也不会开端口。

## 答题方式

| 方式 | 程序做到哪一步 |
| --- | --- |
| 只提示我 | 只提醒有新题，全部自己作答 |
| 只交已保存的答案 | 提交你事先填好的答案；没答案的题只提醒，**不会**调用 AI |
| AI 解答，问过我再交 | AI 答完弹窗给你过目，同意才提交；拒绝或超时都不提交，答案会留着供手动处理 |
| AI 解答并直接交 | 全自动，来不及人工核对 |

限时题的 AI 超时会按剩余时间自动收敛，不会因为等满默认超时而错过。

## AI 接口

地址和模型**不预填**——预置一个陌生网关等于把你的 Key 默认发给第三方，必须自己填。
填好地址和 Key 后可以点「获取列表」拉取该服务支持的模型。

| 格式 | 请求地址 | 说明 |
| --- | --- | --- |
| Anthropic | `{地址}/v1/messages` | Claude、GLM 及各类兼容网关 |
| OpenAI Responses | `{地址}/v1/responses` | Codex 系模型走这个 |
| OpenAI Chat | `{地址}/v1/chat/completions` | 最通用的第三方中转 |
| 通义千问 | 官方 SDK | 需要额外装 `dashscope` |

**思考强度**：关闭 / 最低 / 低 / 中 / 高 / 极高 / 最高。
Anthropic 走 `thinking: adaptive` + `output_config.effort`（`budget_tokens` 已废弃，
新模型会直接拒绝）；OpenAI 走 `reasoning.effort`。
能用哪几档**取决于模型**而不是接口，用不了时会提示你调低一档。

## 文件位置

配置、课件截图、课堂存档都在用户数据目录，设置页有「打开数据目录」：

- macOS：`~/Library/RainClassroomAssistant/`
- Windows：`%APPDATA%\RainClassroomAssistant\`
- Linux：`~/.config/RainClassroomAssistant/`

## 项目结构

```
main.py            入口，创建窗口
Bridge.py          JS ⇄ Python 桥
Scripts/
  App.py           控制器：所有业务状态与流程
  Classes.py       Lesson：签到、websocket 收题、自动答题、弹幕
  AI.py            四种接口格式、思考强度、重试与超时
  Notify.py        系统通知与提示音
  LoginFlow.py     扫码登录
  History.py       课堂存档
  Export.py        课件导出 PDF
  Utils.py         配置读写、HTTP、雨课堂接口
web/               界面（HTML/CSS/JS）
tests/             离线回归测试
```

界面与业务完全分离：`Scripts/` 不依赖任何界面代码，全部逻辑都能脱离界面测试。

## 测试

```bash
for t in tests/test_*.py; do python "$t" || break; done
```

全部不联网、不需要账号。

界面另有一套自检：`web/index.html?mock` 用假数据预览，`web/audit.js` 会走过 28 个
界面状态检查图标尺寸、元素溢出、文字裁切等问题。详见 [tests/README.md](tests/README.md)。
