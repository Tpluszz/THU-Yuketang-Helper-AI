# 清华大学荷塘雨课堂助手 - AI 版

基于 *TrickyDeath* 的项目 [RainClassroomAssistant](https://github.com/TrickyDeath/RainClassroomAssitant) 进行修改，以专门适配清华大学的荷塘雨课堂。

基于 [THU-Yuketang-Helper](https://github.com/zhangchi2004/THU-Yuketang-Helper) 进一步适配，适配无法从前端爬取答案后的荷塘雨课堂。

## 功能

- **自动签到**：检测到课程开始后自动签到并建立监听
- **AI 答题 / 手动答题**：支持在刚上课时答完所有题目，~~然后去愉快摸鱼~~
- **多线程支持**：可以同时监听多门正在上课的课程
- **批量解题**：一键让 AI 解答整门课的未答题目，带进度条，可随时停止
- **可视化界面**：跟随系统的浅色 / 深色主题，分级着色的日志，课程与题目进度一目了然

## 安装

```bash
pip install -r requirements.txt
```

只使用 GLM 的话可以不装 `dashscope`，程序会在选择通义千问时才导入它。

## 使用

```bash
python main.py
```

1. **设置**：点击右上角「设置」，在「AI 服务」页选接口格式、填 API Key，点「测试连接」确认可用。
2. **登录**：点击「登录」，用微信扫描二维码。二维码 60 秒自动刷新，也可手动点「刷新二维码」。
3. **启动监听**：点击「启动监听」（快捷键 `F5`）。检测到正在上课的课程会自动签到并加入列表。
4. **答题**：双击课程名打开题目列表。
   - 「AI 解答全部未答题」会并发调用 AI 解答所有还没有答案的题目
   - 双击单道题可以看大图、手动改答案、单独让 AI 重答，或直接「提交到雨课堂」
   - 已提交到雨课堂的题目会被锁定，批量解答时也会自动跳过

**测试模式**可以在没有课的时候熟悉整套操作，它使用本地示例题目，不会发出任何网络请求。

## 支持的 AI 接口格式

Base URL 只填到域名，路径由所选格式自动补全。**不预填任何默认地址和模型**——
预置一个陌生网关等于把你的 API Key 默认发到第三方服务器上。填好地址和 Key 后，
点「获取模型列表」可以直接从服务端拉取可用模型，不用凭空猜模型名。

| 格式 | 请求地址 | 适用 |
| --- | --- | --- |
| Anthropic | `{Base URL}/v1/messages` | GLM、Claude，以及各类 Anthropic 兼容网关 |
| OpenAI Responses | `{Base URL}/v1/responses` | Codex 等使用 Responses API 的服务 |
| OpenAI Chat Completions | `{Base URL}/v1/chat/completions` | 最通用的第三方中转 |
| 通义千问 dashscope | 官方 SDK | 只需 API Key（[获取方法](https://help.aliyun.com/zh/model-studio/get-api-key)） |

### 思考强度

可选 关闭 / 最低 / 低 / 中 / 高 / 极高，界面上会直接显示这一档实际发出去的参数：

- Anthropic 没有档位概念，映射为 `thinking.budget_tokens`（512 ~ 24576），并自动抬高 `max_tokens`
- OpenAI 两种格式原样透传为 `reasoning.effort` / `reasoning_effort`

各档位能否使用**取决于模型而不是接口**（例如 `xhigh` 需要 gpt-5.1-codex-max 或
gpt-5.3-codex，普通 gpt-5.1-codex 只到 high），所以这里不做白名单限制；
模型不支持时服务端会返回 400，程序会提示你调低一档。

## 答题策略

设置里「课上推送新题目时」决定程序替你做到哪一步，四选一：

| 模式 | 行为 |
| --- | --- |
| 只提示我 | 只在消息区提醒有新题，全部自己动手 |
| 只提交我已保存的答案 | 提交事先填好的答案；**没有答案的题只提醒，绝不调用 AI** |
| 让 AI 解答，弹窗问过我再提交 | AI 解答后弹确认框给你过目，同意才提交；拒绝或超时都不提交，答案保留在题目里供手动处理 |
| 让 AI 解答并直接提交 | 全自动，会即时消耗额度且来不及人工核对 |

另有「提交延迟」（随机或固定秒数，避免秒答）与「确认框等待秒数」（超时按不提交处理，且不会超过题目剩余时间）。

## 文件位置

配置和题目截图存放在用户数据目录，不再依赖启动时的工作目录：

- macOS：`~/Library/RainClassroomAssistant/`
- Windows：`%APPDATA%\RainClassroomAssistant\`
- Linux：`~/.config/RainClassroomAssistant/`

## 项目结构

```
main.py                      入口，DPI 处理与启动错误兜底
Scripts/
  Utils.py                   配置读写、HTTP 会话、雨课堂接口
  Classes.py                 Lesson：签到、websocket 收题、自动答题、弹幕
  AI.py                      多服务商 AI 封装、JSON 解析、重试、连通性测试
UI/
  Theme.py                   配色、字体、ttk 样式与通用小部件
  MainWindow.py              主窗口
  Login.py / Config.py       登录与设置对话框
  ProblemListWindow.py       题目列表 + 批量 AI 解答
  ProblemDetailWindow.py     题目详情 + 单题作答
  TestData.py                测试模式的本地假数据
```
