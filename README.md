# Class Copilot

AI 驱动的本地课堂助手。实时录音转写、自动检测课堂问题并生成回答，支持会话式追问。

## 重构前文档

完整功能基线与可编辑需求见 [项目文档索引](docs/README.md)：

- [功能说明](docs/功能说明.md)：全部页面、业务流程、操作规则和当前限制。
- [重构需求与验收](docs/重构需求与验收.md)：功能去留、实现差异、待决策事项和验收用例。
- [接口与数据字典](docs/接口与数据字典.md)：HTTP / WebSocket、设置、数据模型与迁移参考。

以上文档按当前源码整理；下方概览和 `docs/260519-plan/` 中的早期规划如有差异，以新版文档的现状核对说明为准。

后端：FastAPI + SQLAlchemy (async) + DashScope (Qwen)  
前端：Vite + React + TypeScript + Tailwind CSS  
服务地址：`http://127.0.0.1:29037`

---

## 功能概览

- **实时语音转写** — 基于阿里云 DashScope Qwen Omni Realtime API，支持中文、英文及中英混合
- **自动问题检测** — LLM 分析转写文本，识别课堂中出现的问题
- **自动生成回答** — 对检测到的问题自动生成简要或详细回答（流式输出）
- **会话聊天** — 基于当前课堂上下文进行追问对话
- **课程与会话管理** — 按课程组织，支持按日期筛选
- **录音存档** — 自动编码为 MP3 并保存
- **Markdown 导出** — 导出转写、问答和聊天记录
- **加密存储** — API Key 使用 Fernet 加密后存入数据库
- **音频源灵活切换** — 支持麦克风、系统回环（loopback）、音频文件

---

## 快速开始

### 前置要求

- Python ≥ 3.11
- Node.js ≥ 18（构建前端）
- [uv](https://docs.astral.sh/uv/) 包管理器
- 阿里云 DashScope API Key

### 一键运行

```powershell
# 1. 构建前端
cd frontend
npm install
npm run build
cd ..

# 2. 安装依赖并启动
uv sync
uv run python -m class_copilot
```

浏览器会自动打开 `http://127.0.0.1:29037`。

首次启动自动创建：

```
data/
├── class_copilot.db      # SQLite 数据库
├── .encryption_key       # Fernet 加密密钥
├── logs/                 # 日志（按模块/日期轮转）
└── recordings/           # MP3 录音文件
```

### 前端开发模式
首次启动自动创建：

```
data/
├── class_copilot.db      # SQLite 数据库
├── .encryption_key       # Fernet 加密密钥
├── logs/                 # 日志（按模块/日期轮转）
└── recordings/           # MP3 录音文件
```

### 前端开发模式

需要热更新时同时启动两端：
需要热更新时同时启动两端：

```bash
# 终端 A：后端
uv run python -m class_copilot

# 终端 B：前端（Vite dev server :5173）
cd frontend
npm install
npm run dev
```

Vite 自动将 `/api` 和 `/ws` 代理到后端 `127.0.0.1:29037`。

---

## 配置

### DashScope API Key

进入应用设置页填写，或通过接口设置：

```powershell
Invoke-RestMethod -Method Patch -Uri http://127.0.0.1:29037/api/settings `
  -ContentType "application/json" `
  -Body '{"dashscope_api_key":"sk-xxxx"}'
```

### 环境变量

通过 `CC_` 前缀的环境变量或 `.env` 文件配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CC_DATA_DIR` | `data` | 数据目录路径 |
| `CC_FORCE_IPV4` | `true` | 强制 IPv4 连接 DashScope |
| `CC_DEBUG_AUDIO_FILE` | `false` | 启用文件音频源（调试用） |

### 运行时设置

通过 UI 设置页或 `PATCH /api/settings` 修改，存储在数据库中：

| 设置项 | 默认值 | 说明 |
|--------|--------|------|
| `asr_model` | `qwen3.5-omni-flash-realtime` | ASR 模型 |
| `chat_model_default` | `qwen3.5-plus` | 聊天默认模型 |
| `chat_model_fast` | `qwen3.5-flash` | 聊天快速模型 |
| `auto_answer_model` | `qwen3.5-flash` | 自动回答模型 |
| `auto_answer_type` | `brief` | 回答类型：`brief` / `detailed` |
| `language` | `zh` | 全局语言（`zh` / `en`） |
| `asr_language` | `zh` | ASR 语言（`zh` / `en` / `bilingual`） |
| `audio_source` | `microphone` | 音频源：`microphone` / `loopback` / `file` |
| `vad_threshold` | `0.3` | VAD 阈值 |
| `vad_silence_duration_ms` | `800` | 静音判定时长 (ms) |
| `question_confidence_threshold` | `0.7` | 问题检测置信度阈值 |
| `question_cooldown_seconds` | `15` | 问题检测冷却时间 (s) |
| `question_similarity_threshold` | `0.8` | 问题去重相似度阈值 |

---

## 项目架构

采用六边形架构（Hexagonal Architecture），层次清晰：

```
class_copilot/
├── domain/              # 领域层：端口接口 & 异常定义
│   ├── ports.py         #   RealtimeASRPort, LLMPort
│   └── exceptions.py   #   业务异常
├── application/         # 应用层：用例 & 服务编排
│   ├── session.py       #   SessionService（录音/转写/检测流水线）
│   ├── chat.py          #   ChatService（会话聊天）
│   ├── question.py      #   QuestionDetector, AnswerGenerator
│   └── settings.py      #   SettingsService（运行时配置）
├── api/                 # 接口层：HTTP & WebSocket
│   ├── http/routes.py   #   REST API 路由
│   ├── ws/handlers.py   #   WebSocket 消息分发
│   └── schemas.py       #   请求/响应模型
├── infrastructure/      # 基础设施层：外部集成
│   ├── asr/             #   QwenOmniRealtimeASR（DashScope WebSocket）
│   ├── llm/             #   DashScopeCompatibleLLM（OpenAI 兼容接口）
│   ├── audio/           #   AudioCapture, MP3Encoder, MicLevelMonitor
│   ├── persistence/     #   SQLAlchemy ORM & Repository
│   ├── crypto.py        #   Fernet 加密
│   └── network.py       #   IPv4 补丁
├── config.py            # 应用配置
├── bootstrap.py         # 应用组装 & 生命周期
├── db.py                # 数据库初始化
├── logging.py           # 日志配置
└── __main__.py          # 入口
```

---

## API 接口

### HTTP REST（`/api` 前缀）

**课程管理**
- `GET /api/courses` — 课程列表
- `POST /api/courses` — 创建课程
- `PATCH /api/courses/{id}` — 重命名
- `DELETE /api/courses/{id}` — 删除（仅空课程）

**会话管理**
- `GET /api/sessions` — 会话列表（支持 `date_from`、`date_to`、`course_id` 筛选）
- `GET /api/sessions/{id}` — 会话详情（含转写、问答、聊天）
- `PATCH /api/sessions/{id}` — 修改名称
- `DELETE /api/sessions/{id}` — 删除会话
- `GET /api/sessions/{id}/export.md` — Markdown 导出
- `GET /api/sessions/{id}/recording` — 下载 MP3 录音

**设置**
- `GET /api/settings` — 获取设置（API Key 脱敏）
- `PATCH /api/settings` — 更新设置

**音频**
- `GET /api/audio/devices` — 列出音频设备
- `POST /api/audio/mic-monitor/start` — 开始麦克风电平监测
- `POST /api/audio/mic-monitor/stop` — 停止监测

**状态**
- `GET /api/status` — 当前监听状态

自动文档：`http://127.0.0.1:29037/docs`

### WebSocket（`/ws`）

双向实时通信，消息格式为 JSON。

**客户端 → 服务端：**
- `start_listening` — 开始录音（含 `course_id`、`auto_stop_seconds`）
- `stop_listening` — 停止录音
- `manual_detect` — 手动触发问题检测
- `force_answer` — 强制生成回答
- `chat` — 发送聊天消息
- `update_auto_stop` — 更新自动停止倒计时

**服务端 → 客户端：**
- `transcription` — 转写结果（实时/最终）
- `question_detected` — 检测到问题
- `answer_chunk` / `answer_complete` — 回答流式输出
- `chat_chunk` / `chat_complete` — 聊天流式输出
- `status` — 状态变更
- `mic_level` — 麦克风电平
- `auto_stop_tick` — 自动停止倒计时
- `error` / `notification` — 错误与通知

---

## 数据模型

| 实体 | 说明 |
|------|------|
| Course | 课程 |
| Session | 一次听课会话（属于 Course） |
| Transcription | 转写片段（属于 Session） |
| Question | 检测到的问题（属于 Session） |
| Answer | 问题的回答（属于 Question，按类型唯一） |
| ChatMessage | 聊天消息（属于 Session） |
| Setting | 配置项（支持加密） |

---

## 开发

```powershell
# 安装开发依赖
uv sync --group dev

# 代码检查
uv run ruff check .

# 格式化
uv run ruff format .

# 运行测试
uv run pytest
```

**代码规范：** ruff，行宽 100，目标 Python 3.11+。

---

## 技术栈

| 层 | 技术 |
|----|------|
| Web 框架 | FastAPI + Uvicorn |
| 数据库 | SQLite + SQLAlchemy (async) + aiosqlite |
| ASR | DashScope Qwen Omni Realtime (WebSocket) |
| LLM | DashScope OpenAI 兼容接口 |
| 音频采集 | sounddevice (麦克风) / soundcard (回环) |
| 音频编码 | lameenc (MP3) |
| 加密 | cryptography (Fernet) |
| 日志 | loguru |
| 前端 | React 18 + TypeScript + Tailwind CSS + Zustand |
| 构建 | Vite + Hatch |
