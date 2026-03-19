# 听课助手（class_copilot）— 后端技术方案

> 版本：v1.0
> 日期：2026-03-20

---

## 1. Python 框架选型：FastAPI

**选择：FastAPI**

| 对比项 | FastAPI | Flask |
|--------|---------|-------|
| 异步支持 | 原生 async/await | 需 Quart 或额外插件 |
| WebSocket | 原生支持 | 需 flask-sock 等扩展 |
| 性能 | 基于 Starlette，高性能异步 I/O | 同步模型，并发能力弱 |
| 类型校验 | Pydantic 内置自动校验 | 需手动校验或引入 marshmallow |
| API 文档 | 自动生成 Swagger/ReDoc | 需额外配置 |
| 学习曲线 | 略高 | 低 |

**理由：**

1. **异步是刚需**：本项目核心链路（音频采集 → ASR 流式推送 → LLM 流式生成 → WebSocket 推送）全程异步，FastAPI 原生 async/await 完美匹配
2. **WebSocket 原生支持**：实时转写推送、问题/答案推送均需 WebSocket，FastAPI 基于 Starlette 的 WebSocket 支持成熟稳定
3. **并发处理**：同时处理音频流、多个 ASR 会话、LLM 请求、精修任务等，异步模型的资源利用率远优于同步
4. **Pydantic 模型**：API 请求/响应、数据库模型、配置管理可统一用 Pydantic，减少胶水代码
5. **生态完善**：与 SQLAlchemy（异步）、httpx（异步 HTTP）、websockets 等库无缝配合

**ASGI 服务器：uvicorn**
- 生产级 ASGI 服务器，支持热重载（开发期）
- 启动命令：`uvicorn app.main:app --host 127.0.0.1 --port 8000`

---

## 2. 数据库选型：SQLite + SQLAlchemy (async)

**选择：SQLite**

| 对比项 | SQLite | PostgreSQL |
|--------|--------|------------|
| 部署复杂度 | 零部署，单文件 | 需安装数据库服务 |
| 性能 | 单用户场景完全足够 | 过度设计 |
| 备份 | 拷贝文件即可 | 需 pg_dump |
| 适用场景 | 桌面应用、单用户 | 多用户、高并发 |
| 依赖 | Python 内置 | 需 psycopg2 |

**理由：**

1. **单用户桌面应用**：只有一个用户在本地使用，不存在并发写入问题
2. **零部署**：用户不需要安装任何数据库服务，开箱即用
3. **数据便携**：单个 `.db` 文件，方便备份、迁移
4. **性能足够**：90 分钟课堂产生的数据量（转写文本 + 问答记录）对 SQLite 毫无压力
5. **WAL 模式**：启用 WAL 模式可同时读写，满足边写入转写边查询历史的需求

**ORM：SQLAlchemy 2.0 (async)**
- 使用 `aiosqlite` 驱动实现异步访问
- SQLAlchemy 2.0 新式 API，类型友好
- 支持 Alembic 数据库迁移

```python
# 连接示例
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    "sqlite+aiosqlite:///data/class_copilot.db",
    echo=False,
    connect_args={"check_same_thread": False}
)
```

**关键表设计概览：**

```
sessions          — 课堂会话（日期、课程名、状态、精修状态等）
recordings        — 录音文件（关联会话，文件路径，时长等）
transcripts       — 转写片段（实时版/精修版文本、说话人、时间戳等）
questions         — 检测到的问题（来源、置信度等）
answers           — 生成的答案（简洁版/展开版、关联问题等）
active_qas        — 主动提问记录
speaker_profiles  — 声纹档案（课程+教师名、声纹特征引用等）
courses           — 课程信息（名称、热词列表等）
settings          — 用户配置（加密存储）
refine_tasks      — 精修任务队列（状态、进度、重试次数等）
```

---

## 3. 音频采集方案：PyAudio + sounddevice（混合方案）

**主方案：sounddevice（推荐）**
**备选：PyAudio**

| 对比项 | sounddevice | PyAudio |
|--------|-------------|---------|
| 安装 | `pip install sounddevice`，纯 wheel | 需编译 portaudio，Windows 上常有安装问题 |
| API 风格 | 现代 Pythonic，支持回调和阻塞 | C 风格 API 封装 |
| 异步友好 | 回调模式天然适合异步架构 | 阻塞式读取 |
| 维护状态 | 活跃维护 | 维护较少 |
| numpy 集成 | 内置 | 需手动转换 |

**理由：**

1. **安装无痛**：sounddevice 在 Windows 上通过 pip 直接安装，无需额外编译依赖
2. **回调模式**：音频数据通过回调函数推送，不阻塞主线程，完美配合异步架构
3. **设备枚举**：`sounddevice.query_devices()` 直接列出所有可用麦克风设备
4. **numpy 集成**：音频数据直接以 numpy array 形式提供，方便处理

**音频参数：**

```python
SAMPLE_RATE = 16000      # 16kHz，ASR 标准采样率
CHANNELS = 1             # 单声道
DTYPE = "int16"          # 16-bit PCM
CHUNK_DURATION = 0.1     # 100ms 每块，兼顾延迟和效率
```

**MP3 录音保存：pydub + ffmpeg（或 lameenc）**

```python
# 方案 A：pydub（依赖 ffmpeg）
from pydub import AudioSegment

# 方案 B：lameenc（纯 Python MP3 编码，无外部依赖）
import lameenc
encoder = lameenc.Encoder()
encoder.set_bit_rate(128)
encoder.set_in_sample_rate(16000)
encoder.set_channels(1)
```

**推荐方案 B（lameenc）**：无需用户安装 ffmpeg，减少部署依赖。实时编码为 MP3 块，定期刷写磁盘，防崩溃丢失。

**音频处理流程：**

```
麦克风 → sounddevice 回调(PCM) → asyncio.Queue
                                      ↓
                              ┌───────┴───────┐
                              ↓               ↓
                       ASR WebSocket      MP3 编码器
                       (实时转写)        (录音保存)
```

---

## 4. ASR 对接方案：DashScope 实时语音识别

### 4.1 实时 ASR（核心层）

**协议：DashScope Gummy 实时语音识别 WebSocket API**

**SDK：dashscope Python SDK**

```python
# 使用 dashscope SDK 的实时语音识别
import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback

class RealtimeASRCallback(RecognitionCallback):
    def on_event(self, result):
        # 中间结果 / 最终结果
        pass

recognition = Recognition(
    model="paraformer-realtime-v2",  # 实时模型
    format="pcm",
    sample_rate=16000,
    callback=RealtimeASRCallback(),
    # 热词
    language_hints=["zh", "en"],
)
recognition.start()
recognition.send_audio_frame(audio_bytes)
recognition.stop()
```

**关键特性支持：**

| 需求 | DashScope 实现 |
|------|---------------|
| 中英混合 | `language_hints=["zh", "en"]` |
| 热词 | `vocabulary_id` 或 `hotwords` 参数 |
| 说话人分离（diarization） | `diarization_enabled=True` |
| 中间结果 | `enable_intermediate_result=True` |
| 断网重连 | SDK 内置重连 + 应用层重连逻辑 |

**实时 ASR 模型选择：**
- `paraformer-realtime-v2`：中文为主，低延迟
- `paraformer-v2`：中英混合，精度更高
- 支持在设置中切换模型

### 4.2 高精度精修 ASR（增强层）

**模型：qwen3-asr-flash（文件转写）**

```python
# 文件转写 API
from dashscope.audio.asr import Transcription

task = Transcription.async_call(
    model="qwen3-asr-flash",
    file_urls=[audio_file_url],  # 或本地文件路径
    language_hints=["zh", "en"],
    hotwords="专业术语1,专业术语2",
)

# 轮询结果
result = Transcription.wait(task.output.task_id)
```

**精修调度策略：**
- 课后批量：`session.stop()` 后自动提交全部录音
- 课中定时：后台定时器每 N 分钟提交最近录音片段
- 手动触发：API 端点 + 快捷键触发
- 使用 asyncio 任务队列管理，支持暂停/恢复/取消

---

## 5. LLM 对接方案：DashScope + OpenAI 兼容接口

### 5.1 模型选择

| 场景 | 推荐模型 | 理由 |
|------|---------|------|
| 问题检测 | qwen-turbo-latest | 快速、低成本、判断任务足够 |
| 自动答案生成（简洁版） | qwen-turbo-latest | 速度优先，≤3s |
| 自动答案生成（展开版） | qwen-plus-latest | 质量更高 |
| 主动提问（快速模式） | qwen-plus-latest | 平衡速度和质量 |
| 主动提问（高质量模式） | qwen-max-latest | 最强模型 |
| 主动提问（深度思考） | qwq-plus-latest | 推理能力强 |
| 英文翻译 | qwen-turbo-latest | 快速翻译 |

### 5.2 接入方式

**使用 OpenAI 兼容接口（推荐）**：DashScope 提供 OpenAI 兼容端点，可统一用 `openai` SDK 调用，方便未来切换模型/提供商。

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key=dashscope_api_key,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# 流式生成答案
async def generate_answer(context: str, question: str):
    stream = await client.chat.completions.create(
        model="qwen-turbo-latest",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"上下文：{context}\n问题：{question}"}
        ],
        stream=True,
    )
    async for chunk in stream:
        yield chunk.choices[0].delta.content
```

### 5.3 并行策略

- 问题检测 → 检测到问题后，**并行**启动简洁版和展开版答案生成
- 使用 `asyncio.gather()` 并行调用
- 每个 LLM 调用使用独立的流式 WebSocket 推送通道

### 5.4 Prompt 管理

- 所有 Prompt 模板集中在 `app/prompts/` 目录
- 使用 Jinja2 或 Python f-string 模板
- 支持课程名、语言、上下文窗口等变量注入

---

## 6. WebSocket 方案：FastAPI 原生 WebSocket

### 6.1 架构设计

```
浏览器 ←→ WebSocket ←→ FastAPI 后端
            |
   ┌────────┼────────┐
   ↓        ↓        ↓
 转写推送  问答推送  状态推送
```

**单 WebSocket 连接 + 消息类型分发**（推荐）

理由：减少连接数，浏览器对同域 WebSocket 连接数有限制，统一管理更简单。

### 6.2 消息协议

```json
{
    "type": "transcript",           // 消息类型
    "data": {
        "text": "...",
        "is_final": true,
        "speaker": "teacher",
        "timestamp": 1234567890.123
    }
}
```

**消息类型枚举：**

| type | 方向 | 说明 |
|------|------|------|
| `transcript` | Server→Client | 转写片段（中间/最终） |
| `question_detected` | Server→Client | 检测到问题 |
| `answer_chunk` | Server→Client | 答案流式片段 |
| `answer_complete` | Server→Client | 答案生成完成 |
| `active_qa_chunk` | Server→Client | 主动提问回答片段 |
| `refine_status` | Server→Client | 精修状态更新 |
| `refine_update` | Server→Client | 精修文本替换 |
| `status` | Server→Client | 系统状态变更 |
| `error` | Server→Client | 错误通知 |
| `command` | Client→Server | 客户端指令（开始/停止等） |
| `active_question` | Client→Server | 主动提问 |

### 6.3 连接管理

```python
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    async def broadcast(self, message: dict):
        for conn in self.active_connections:
            await conn.send_json(message)
```

### 6.4 断线重连

- 前端：检测到连接断开后，指数退避重连（1s → 2s → 4s → 8s → 16s，上限 30s）
- 后端：为每个会话维护消息缓冲区，重连后推送缺失消息
- 心跳：每 30s ping/pong，超时 60s 判定断线

---

## 7. 系统托盘方案：pystray

**选择：pystray**

```python
import pystray
from PIL import Image

def create_tray():
    icon = pystray.Icon(
        "class_copilot",
        icon=Image.open("assets/icon.png"),
        title="听课助手",
        menu=pystray.Menu(
            pystray.MenuItem("打开浏览器", on_open_browser),
            pystray.MenuItem("开始监听", on_toggle_listen),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", on_quit),
        )
    )
    icon.run()
```

**理由：**
1. 跨平台（虽然目前只需 Windows，但不锁死）
2. API 简洁，依赖少（仅需 `Pillow`）
3. 支持动态更新图标（可用于显示录音状态）
4. 支持 Windows 原生通知（`icon.notify()`，用于问题检测提醒）

**状态图标：**
- 🟢 就绪（绿色）
- 🔴 录音中（红色/动画）
- 🟡 重连中（黄色）
- ⚫ 已停止（灰色）

**线程模型：**
- pystray 自身运行在独立线程
- 通过 `asyncio.run_coroutine_threadsafe()` 与 FastAPI 事件循环通信

---

## 8. 全局快捷键方案：keyboard

**选择：keyboard 库**

| 对比项 | keyboard | pynput | global-hotkeys |
|--------|----------|--------|----------------|
| 全局监听 | ✅ 原生支持 | ✅ 支持 | ✅ 支持 |
| 组合键 | ✅ `keyboard.add_hotkey("ctrl+shift+s", ...)` | 需手动管理状态机 | ✅ 支持 |
| Windows 支持 | ✅ 最佳 | ✅ 一般 | ✅ 一般 |
| 管理员权限 | 不需要（大部分场景） | 不需要 | 不需要 |
| API 简洁度 | 极简 | 中等 | 中等 |

**理由：**
1. **API 极简**：一行代码注册全局快捷键
2. **Windows 优化好**：底层使用 Windows Hook API
3. **组合键友好**：`ctrl+shift+s` 直接识别，无需手动管理状态
4. **支持热键动态注册/注销**：用户自定义快捷键时可动态更新

```python
import keyboard

class HotkeyManager:
    def __init__(self, event_loop):
        self.loop = event_loop
        self.hotkeys = {}

    def register_defaults(self):
        mappings = {
            "ctrl+shift+s": self._toggle_listen,
            "ctrl+shift+q": self._manual_detect,
            "ctrl+shift+h": self._toggle_window,
            "ctrl+shift+c": self._copy_answer,
            "ctrl+shift+t": self._toggle_answer_mode,
            "ctrl+shift+a": self._focus_ask,
            "ctrl+shift+f": self._toggle_filter,
            "ctrl+shift+r": self._manual_refine,
        }
        for key, callback in mappings.items():
            self.hotkeys[key] = keyboard.add_hotkey(key, callback)

    def _toggle_listen(self):
        asyncio.run_coroutine_threadsafe(
            self.app_service.toggle_listen(), self.loop
        )
```

**线程模型：**
- keyboard 监听需运行在独立线程（内部已处理）
- 回调中通过 `asyncio.run_coroutine_threadsafe()` 调度到主事件循环

---

## 9. 日志记录方案：loguru

**选择：loguru**

| 对比项 | loguru | logging（标准库） |
|--------|--------|-------------------|
| 配置复杂度 | 零配置即可使用 | 需配置 handler/formatter |
| 输出格式 | 自带彩色、结构化 | 需自定义 |
| 异常追踪 | 自动捕获完整 traceback | 需手动 `exc_info=True` |
| 文件轮转 | 内置 rotation/retention | 需 RotatingFileHandler |
| 线程安全 | ✅ | ✅ |
| 异步支持 | `enqueue=True` 异步写入 | 需 QueueHandler |
| 过滤 | 灵活的 filter 函数 | 基于 logger name |

**理由：**
1. **零配置**：`from loguru import logger` 即可使用，开发效率高
2. **自动异常追踪**：`@logger.catch` 装饰器自动捕获并记录异常的完整上下文
3. **异步安全**：`enqueue=True` 通过队列写入，不阻塞 async 协程
4. **文件轮转**：内置支持按大小/时间轮转，自动清理旧日志
5. **结构化日志**：支持 JSON 格式输出，方便后续分析

```python
from loguru import logger
import sys

def setup_logging(log_dir: str = "logs"):
    # 移除默认处理器
    logger.remove()

    # 控制台输出（开发时）
    logger.add(
        sys.stderr,
        level="DEBUG",
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    )

    # 文件输出（生产）
    logger.add(
        f"{log_dir}/class_copilot_{{time:YYYY-MM-DD}}.log",
        level="INFO",
        rotation="50 MB",        # 50MB 轮转
        retention="30 days",     # 保留 30 天
        compression="zip",       # 压缩旧日志
        encoding="utf-8",
        enqueue=True,            # 异步写入，不阻塞事件循环
    )

    # 错误日志单独存放
    logger.add(
        f"{log_dir}/error_{{time:YYYY-MM-DD}}.log",
        level="ERROR",
        rotation="20 MB",
        retention="90 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
    )
```

**日志分类：**

| 模块 | 日志内容 |
|------|---------|
| `audio` | 音频采集状态、设备变化、录音文件路径 |
| `asr` | ASR 连接/断开、转写结果、错误重试 |
| `llm` | LLM 请求/响应摘要、token 用量、延迟 |
| `refine` | 精修任务提交/完成/失败、进度 |
| `ws` | WebSocket 连接/断开、消息统计 |
| `hotkey` | 快捷键触发 |
| `db` | 数据库操作（关键操作） |

---

## 10. 项目目录结构

```
class_copilot/
├── app/                            # 后端应用主目录
│   ├── __init__.py
│   ├── main.py                     # FastAPI 应用入口 & uvicorn 启动
│   ├── config.py                   # 配置管理（Pydantic Settings）
│   │
│   ├── api/                        # HTTP API 路由
│   │   ├── __init__.py
│   │   ├── sessions.py             # 会话管理 API（CRUD）
│   │   ├── recordings.py           # 录音管理 API
│   │   ├── transcripts.py          # 转写记录 API
│   │   ├── questions.py            # 问答记录 API
│   │   ├── settings.py             # 设置 API（含 API Key 加密）
│   │   ├── courses.py              # 课程管理 API（热词等）
│   │   ├── speakers.py             # 说话人/声纹管理 API
│   │   ├── audio_devices.py        # 音频设备列表 API
│   │   └── refine.py               # 精修任务管理 API
│   │
│   ├── ws/                         # WebSocket 处理
│   │   ├── __init__.py
│   │   ├── handler.py              # WebSocket 连接管理 & 消息分发
│   │   └── protocol.py             # 消息协议定义（类型枚举、数据模型）
│   │
│   ├── services/                   # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── audio_service.py        # 音频采集、MP3 编码、录音管理
│   │   ├── asr_service.py          # 实时 ASR 对接（DashScope 实时流式）
│   │   ├── refine_service.py       # 高精度精修 ASR（qwen3-asr-flash）
│   │   ├── llm_service.py          # LLM 统一调用（问题检测、答案生成等）
│   │   ├── question_detector.py    # 问题检测逻辑（去重、冷却、置信度）
│   │   ├── answer_generator.py     # 答案生成（简洁/展开、并行）
│   │   ├── active_qa_service.py    # 主动提问服务
│   │   ├── translation_service.py  # 英文翻译服务
│   │   ├── speaker_service.py      # 说话人识别 & 声纹管理
│   │   ├── session_service.py      # 会话生命周期管理（开始/停止/续记）
│   │   ├── notification_service.py # Windows 通知（通过 pystray）
│   │   ├── export_service.py       # 导出（Markdown 格式）
│   │   └── clipboard_service.py    # 剪贴板操作
│   │
│   ├── models/                     # 数据库模型（SQLAlchemy ORM）
│   │   ├── __init__.py
│   │   ├── base.py                 # Base, engine, session 工厂
│   │   ├── session.py              # Session 模型
│   │   ├── recording.py            # Recording 模型
│   │   ├── transcript.py           # Transcript 模型
│   │   ├── question.py             # Question 模型
│   │   ├── answer.py               # Answer 模型
│   │   ├── active_qa.py            # ActiveQA 模型
│   │   ├── speaker.py              # Speaker 模型
│   │   ├── course.py               # Course 模型
│   │   └── refine_task.py          # RefineTask 模型
│   │
│   ├── schemas/                    # Pydantic 数据模型（API 请求/响应）
│   │   ├── __init__.py
│   │   ├── session.py
│   │   ├── transcript.py
│   │   ├── question.py
│   │   ├── answer.py
│   │   ├── settings.py
│   │   ├── course.py
│   │   ├── speaker.py
│   │   └── ws_messages.py          # WebSocket 消息模型
│   │
│   ├── prompts/                    # LLM Prompt 模板
│   │   ├── __init__.py
│   │   ├── question_detect.py      # 问题检测 prompt
│   │   ├── answer_brief.py         # 简洁版答案 prompt
│   │   ├── answer_detailed.py      # 展开版答案 prompt
│   │   ├── active_qa.py            # 主动提问 prompt
│   │   └── translation.py          # 翻译 prompt
│   │
│   ├── core/                       # 核心基础设施
│   │   ├── __init__.py
│   │   ├── security.py             # API Key 加密/解密（cryptography.Fernet）
│   │   ├── logging.py              # loguru 日志配置
│   │   ├── events.py               # 内部事件总线（pub/sub）
│   │   └── exceptions.py           # 自定义异常
│   │
│   └── system/                     # 系统集成
│       ├── __init__.py
│       ├── tray.py                 # 系统托盘（pystray）
│       ├── hotkeys.py              # 全局快捷键（keyboard）
│       └── browser.py              # 浏览器启动管理
│
├── frontend/                       # 前端静态文件（由 FastAPI 直接 serve）
│   ├── index.html
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   ├── app.js                  # 主应用逻辑
│   │   ├── websocket.js            # WebSocket 客户端
│   │   ├── transcript.js           # 转写显示
│   │   ├── answers.js              # 答案卡片
│   │   ├── ask.js                  # 主动提问
│   │   ├── history.js              # 历史浏览
│   │   └── settings.js             # 设置面板
│   └── assets/
│       └── icons/
│
├── data/                           # 运行时数据（gitignore）
│   ├── class_copilot.db            # SQLite 数据库
│   └── recordings/                 # 录音文件（按日期/课程归档）
│       └── 2026-03-20_思政课/
│           ├── part_001.mp3
│           └── part_002.mp3
│
├── logs/                           # 日志文件（gitignore）
│   ├── class_copilot_2026-03-20.log
│   └── error_2026-03-20.log
│
├── assets/                         # 应用资源
│   ├── icon.ico                    # 托盘图标
│   └── icon.png
│
├── migrations/                     # Alembic 数据库迁移
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│
├── tests/                          # 测试
│   ├── __init__.py
│   ├── test_asr_service.py
│   ├── test_llm_service.py
│   ├── test_question_detector.py
│   └── test_answer_generator.py
│
├── docs/                           # 文档
│   ├── requirements-v2.md
│   └── backend-architecture.md
│
├── .env.example                    # 环境变量模板
├── .gitignore
├── pyproject.toml                  # 项目配置 & 依赖管理（推荐 uv/pdm）
├── requirements.txt                # pip 依赖（兼容）
└── README.md
```

---

## 11. 关键第三方依赖列表

### 核心框架

| 包名 | 用途 | 必需 |
|------|------|------|
| `fastapi` | Web 框架 | ✅ |
| `uvicorn[standard]` | ASGI 服务器 | ✅ |
| `websockets` | WebSocket 底层（uvicorn 依赖） | ✅ |

### 数据库

| 包名 | 用途 | 必需 |
|------|------|------|
| `sqlalchemy[asyncio]` | ORM（异步） | ✅ |
| `aiosqlite` | SQLite 异步驱动 | ✅ |
| `alembic` | 数据库迁移 | ✅ |

### 音频处理

| 包名 | 用途 | 必需 |
|------|------|------|
| `sounddevice` | 音频采集（麦克风） | ✅ |
| `numpy` | 音频数据处理 | ✅ |
| `lameenc` | PCM → MP3 实时编码 | ✅ |

### AI/ASR/LLM

| 包名 | 用途 | 必需 |
|------|------|------|
| `dashscope` | 阿里百炼 ASR SDK（实时+文件转写） | ✅ |
| `openai` | LLM 调用（OpenAI 兼容接口） | ✅ |

### 系统集成

| 包名 | 用途 | 必需 |
|------|------|------|
| `pystray` | 系统托盘 | ✅ |
| `Pillow` | 托盘图标加载（pystray 依赖） | ✅ |
| `keyboard` | 全局快捷键 | ✅ |
| `pyperclip` | 跨平台剪贴板 | ✅ |

### 安全

| 包名 | 用途 | 必需 |
|------|------|------|
| `cryptography` | API Key 加密（Fernet） | ✅ |

### 日志

| 包名 | 用途 | 必需 |
|------|------|------|
| `loguru` | 日志记录 | ✅ |

### 开发工具

| 包名 | 用途 | 必需 |
|------|------|------|
| `pytest` | 测试框架 | 开发 |
| `pytest-asyncio` | 异步测试 | 开发 |
| `httpx` | 异步 HTTP 测试客户端 | 开发 |
| `ruff` | Linter + Formatter | 开发 |

### requirements.txt 完整清单

```txt
# 核心框架
fastapi>=0.115.0
uvicorn[standard]>=0.34.0

# 数据库
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.20.0
alembic>=1.14.0

# 音频
sounddevice>=0.5.0
numpy>=1.26.0
lameenc>=1.7.0

# AI
dashscope>=1.22.0
openai>=1.60.0

# 系统
pystray>=0.19.0
Pillow>=10.0.0
keyboard>=0.13.5
pyperclip>=1.9.0

# 安全
cryptography>=43.0.0

# 日志
loguru>=0.7.0
```

---

## 12. 核心架构图

```
┌─────────────────────────────────────────────────────────┐
│                      浏览器前端                          │
│   (HTML/CSS/JS, served by FastAPI static files)         │
└────────────┬───────────────┬────────────────────────────┘
             │ HTTP REST     │ WebSocket
             ↓               ↓
┌────────────┴───────────────┴────────────────────────────┐
│                    FastAPI 应用层                         │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ REST API │  │ WS Handler   │  │ Static Files     │   │
│  └────┬─────┘  └──────┬───────┘  └──────────────────┘   │
│       │               │                                  │
│  ┌────┴───────────────┴──────────────────────────────┐   │
│  │               Service 业务逻辑层                    │   │
│  │  ┌─────────┐ ┌──────────┐ ┌────────────────────┐  │   │
│  │  │ Audio   │ │ ASR      │ │ LLM                │  │   │
│  │  │ Service │→│ Service  │→│ (Detect+Answer+QA) │  │   │
│  │  └─────────┘ └──────────┘ └────────────────────┘  │   │
│  │  ┌─────────┐ ┌──────────┐ ┌────────────────────┐  │   │
│  │  │ Refine  │ │ Speaker  │ │ Session            │  │   │
│  │  │ Service │ │ Service  │ │ Service             │  │   │
│  │  └─────────┘ └──────────┘ └────────────────────┘  │   │
│  └───────────────────┬───────────────────────────────┘   │
│                      │                                    │
│  ┌───────────────────┴───────────────────────────────┐   │
│  │           数据访问层 (SQLAlchemy Async)              │   │
│  │           SQLite + aiosqlite                       │   │
│  └────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                    系统集成层（独立线程）                    │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │ pystray     │  │ keyboard    │  │ Browser Launcher │  │
│  │ 系统托盘     │  │ 全局快捷键   │  │ 浏览器启动        │  │
│  └─────────────┘  └─────────────┘  └──────────────────┘  │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                    外部服务（云端）                         │
│  ┌─────────────────┐  ┌─────────────────────────────┐    │
│  │ DashScope ASR   │  │ DashScope LLM              │    │
│  │ (实时+文件转写)  │  │ (qwen-turbo/plus/max/qwq)  │    │
│  └─────────────────┘  └─────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

---

## 13. 核心数据流

### 13.1 实时转写 → 问题检测 → 答案生成

```
麦克风 PCM
    │
    ├──→ MP3 编码 → 写入磁盘（录音文件）
    │
    └──→ DashScope ASR WebSocket
             │
             ├── 中间结果 ──→ WS 推送前端（灰色文字）
             │
             └── 最终结果 ──→ 写入数据库
                              │
                              └──→ 问题检测（LLM）
                                       │
                                       ├── 非问题 → 跳过
                                       │
                                       └── 检测到问题
                                            │
                                            ├──→ WS 推送（问题通知）
                                            ├──→ Windows 通知
                                            ├──→ 写入数据库
                                            │
                                            └──→ 并行生成答案
                                                  ├── 简洁版 → 流式 WS 推送
                                                  └── 展开版 → 流式 WS 推送
```

### 13.2 精修流程

```
录音 MP3 文件
    │
    └──→ qwen3-asr-flash（文件转写）
              │
              └── 精修结果返回
                   │
                   ├──→ 更新数据库（精修版文本）
                   ├──→ WS 推送（静默替换前端文本）
                   │
                   └──→ 二次补检（可选）
                         │
                         ├── 补检到新问题 → 生成答案 → 通知/存储
                         └── 已有问题 → 更新问题描述（精修版）
```

---

## 14. 启动流程

```python
# app/main.py 核心流程
import asyncio
import threading
import webbrowser
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="听课助手")

# 挂载前端静态文件
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

@app.on_event("startup")
async def startup():
    # 1. 初始化数据库（创建表、运行迁移）
    await init_database()
    # 2. 加载配置
    await load_settings()
    # 3. 启动系统托盘（独立线程）
    threading.Thread(target=start_tray, daemon=True).start()
    # 4. 注册全局快捷键（keyboard 内部线程）
    register_hotkeys(asyncio.get_event_loop())
    # 5. 打开浏览器
    webbrowser.open("http://127.0.0.1:8000")

@app.on_event("shutdown")
async def shutdown():
    # 清理资源：停止录音、关闭 ASR 连接、保存状态
    await cleanup()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
```

---

## 15. 技术风险 & 应对

| 风险 | 影响 | 应对策略 |
|------|------|---------|
| DashScope 实时 ASR 断连 | 转写中断 | SDK 内置重连 + 应用层 3 次重试 + 指数退避 |
| LLM API 延迟波动 | 答案生成慢 | 流式输出先显示部分、超时降级用 faster 模型 |
| 笔记本麦克风质量差 | 识别准确率低 | 热词补偿 + 精修层兜底 |
| 90 分钟长时间运行 | 内存泄漏 | 定期清理转写缓冲区，限制上下文窗口大小 |
| SQLite 文件锁 | 并发写入冲突 | WAL 模式 + 单写入队列 |
| keyboard 库冲突 | 快捷键失效 | 提供设置界面自定义快捷键 + 备选 pynput |
