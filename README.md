# 听课助手 (Class Copilot)

> 实时听课辅助工具 — 课堂语音转写、问题检测与智能答案生成。

面向大学课堂场景的桌面端应用，基于 FastAPI + WebSocket 构建，支持实时语音识别、教师提问自动检测、AI 答案生成、高精度转写精修及完整的课堂记录归档。

## 快速开始

### 环境要求

- Python ≥ 3.10
- Windows 操作系统（系统托盘与通知依赖 Win32 API）

### 安装与启动

```bash
# 克隆仓库
git clone https://github.com/tianzheng-zhou/class_copilot.git
cd class_copilot

# 安装依赖（开发模式）
pip install -e .

# 或使用 requirements.txt
pip install -r requirements.txt

# 启动应用
python -m class_copilot
# 或
python run.py
```

启动后自动打开浏览器访问 `http://127.0.0.1:8765`，同时在系统托盘显示图标。

## 功能概览

- **实时语音转写**：支持中英文及混合语言，流式 WebSocket 推送
- **多 ASR 引擎**：DashScope（阿里百炼）/ 豆包（火山引擎），可配置切换
- **问题自动检测**：LLM 驱动的教师提问识别，去重 + 冷却 + 置信度过滤
- **智能答案生成**：简洁版 + 展开版双答案并行生成，流式输出
- **主动提问**：课堂中实时向 AI 提问，支持上下文关联
- **高精度精修**：课后/课中/手动三种策略，离线 ASR 二次转写 + 精修后问题复查
- **课堂录音**：MP3 实时编码保存，支持续记分段
- **课程管理**：多课程支持，热词定制，语言设置
- **历史记录**：完整的转写、问答、聊天记录归档，支持 Markdown 导出
- **加密存储**：API Key 等敏感配置 Fernet 加密落库
- **OSS 上传**（可选）：录音文件上传阿里云 OSS，供豆包离线 ASR 访问
- **系统托盘**：后台运行，全局快捷键操作，Windows 通知弹窗
- **断线自动重连**：ASR WebSocket 异常断开后自动重连（最多 3 轮）

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│              SessionManager（中枢单例）               │
│              协调所有服务的生命周期与消息路由            │
└────────────────────────┬────────────────────────────┘
       ┌────────┬────────┼────────┬──────────┬────────┐
       ↓        ↓        ↓        ↓          ↓        ↓
  AudioSvc  ASRSvc  LLMSvc  QuestionDet  RefineSvc  NotifySvc
   录音+编码  实时转写  答案生成   问题检测     精修转写   系统通知
```

**技术栈**：

| 层面 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| 实时通信 | WebSocket |
| 数据库 | SQLite + SQLAlchemy (async) + WAL 模式 |
| 音频采集 | sounddevice (PCM 16kHz) |
| MP3 编码 | lameenc |
| 日志 | loguru（分类日志 + 自动轮转） |
| 系统集成 | pystray (托盘) + keyboard (快捷键) + win10toast (通知) |

## ASR 引擎

| 引擎 | 用途 | 模型 |
|------|------|------|
| DashScope | 实时转写 | `paraformer-realtime-v2` |
| DashScope | 离线精修 | `paraformer-v2` |
| 豆包 (火山引擎) | 实时转写 | Seed ASR 大模型 (streaming) |
| 豆包 (火山引擎) | 离线精修 | Seed ASR 大模型 (offline) |

通过 `CC_ASR_PROVIDER` 和 `CC_REFINEMENT_PROVIDER` 分别配置实时和精修引擎。

## LLM 集成

基于 OpenAI 兼容接口（默认 DashScope），支持多模型分工：

| 功能 | 默认模型 | 说明 |
|------|---------|------|
| 问题检测 | `qwen-turbo-latest` | 快速 JSON 输出判断疑问句 |
| 简洁版答案 | `qwen3.5-flash` | 2-3 句快速响应 |
| 展开版答案 | `qwen3.5-plus` | 5-8 句详细回答 |
| 主动提问 | `qwen3.5-quality` | 深度回答，Markdown 格式 |

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| Ctrl+Shift+S | 开始/停止监听 |
| Ctrl+Shift+Q | 手动触发问题检测 |
| Ctrl+Shift+H | 隐藏/显示窗口 |
| Ctrl+Shift+C | 复制最新答案 |
| Ctrl+Shift+T | 切换简洁版/展开版 |
| Ctrl+Shift+A | 呼出提问界面 |
| Ctrl+Shift+F | 切换 LLM 输入过滤模式 (teacher_only ↔ all) |
| Ctrl+Shift+R | 手动触发精修 |

## WebSocket 协议

端点：`ws://127.0.0.1:8765/ws`

消息格式统一为 JSON，包含 `type` 和 `data` 字段。

### 客户端 → 服务端

| type | 说明 |
|------|------|
| `start_listening` | 开始监听（携带课程 ID 和续记标志） |
| `stop_listening` | 停止监听 |
| `manual_detect` | 手动触发问题检测 |
| `chat` | 主动提问 |
| `toggle_filter_mode` | 切换 LLM 输入过滤模式 |
| `manual_refine` | 手动触发精修 |

### 服务端 → 客户端

| type | 说明 |
|------|------|
| `transcript` | 实时转写片段 |
| `question_detected` | 检测到问题 |
| `answer_chunk` / `answer_complete` | 答案流式片段 / 完成 |
| `chat_chunk` / `chat_complete` | 主动提问回答流式片段 / 完成 |
| `refine_update` / `refine_status` | 精修文本替换 / 进度更新 |
| `status` / `error` | 系统状态与错误 |

## REST API

所有接口前缀 `/api`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/courses` | 课程列表 |
| POST | `/api/courses` | 创建课程 |
| PUT | `/api/courses/{id}` | 更新课程 |
| GET | `/api/sessions` | 历史会话列表 |
| GET | `/api/sessions/{id}` | 会话详情（含转写、问答、聊天） |
| DELETE | `/api/sessions/{id}` | 删除会话及关联数据 |
| GET | `/api/sessions/{id}/export` | 导出会话为 Markdown |
| GET | `/api/settings` | 获取设置（密钥带预览） |
| PUT | `/api/settings` | 更新设置（支持加密） |
| GET | `/api/settings/runtime` | 获取运行时配置 |
| PUT | `/api/settings/runtime` | 批量更新运行时配置 |
| GET | `/api/recordings/{filename}` | 下载录音文件 |

## 数据库

SQLite 数据库，WAL 模式，表结构：

| 表 | 说明 |
|---|------|
| `courses` | 课程（名称、语言、热词） |
| `sessions` | 课堂会话（状态、精修状态） |
| `recordings` | 录音文件（MP3 路径、时长、序号） |
| `transcriptions` | 转写片段（实时文本 + 精修文本、说话人角色、时间戳） |
| `questions` | 检测到的问题（来源、置信度） |
| `answers` | 生成的答案（简洁版 + 展开版） |
| `chat_messages` | 主动提问对话记录 |
| `voiceprints` | 声纹档案（教师识别） |
| `settings` | 键值配置（支持加密） |
| `refinement_tasks` | 精修任务队列 |

## 配置

支持 `.env` 文件或数据库设置，环境变量前缀 `CC_`。

<details>
<summary>完整配置项列表</summary>

### ASR 配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CC_ASR_PROVIDER` | 实时 ASR 引擎 | `dashscope` |
| `CC_REFINEMENT_PROVIDER` | 精修 ASR 引擎 | `dashscope` |
| `CC_DASHSCOPE_API_KEY` | DashScope API Key | — |
| `CC_DOUBAO_APPID` | 豆包 App ID | — |
| `CC_DOUBAO_ACCESS_TOKEN` | 豆包 Access Token | — |
| `CC_DOUBAO_RESOURCE_ID_STREAMING` | 豆包实时资源 ID | `volc.seedasr.sauc.duration` |
| `CC_DOUBAO_RESOURCE_ID_OFFLINE` | 豆包离线资源 ID | `volc.seedasr.auc` |

### LLM 配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CC_LLM_BASE_URL` | LLM API 基址 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `CC_LLM_MODEL_FAST` | 快速模型 | `qwen3.5-flash` |
| `CC_LLM_MODEL_QUALITY` | 高质量模型 | `qwen3.5-plus` |
| `CC_AUTO_ANSWER_MODEL` | 自动答案模型 | `qwen3.5-flash` |

### 精修配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CC_ENABLE_REFINEMENT` | 启用精修 | `false` |
| `CC_REFINEMENT_STRATEGY` | 精修策略 (post/periodic/manual) | `post` |
| `CC_REFINEMENT_INTERVAL_MINUTES` | 定时精修间隔 | `5` |
| `CC_REFINEMENT_MAX_MINUTES` | 最大精修时长 | `90` |
| `CC_ENABLE_REFINEMENT_RECHECK` | 精修后问题复查 | `true` |
| `CC_ENABLE_REFINEMENT_ANSWER_UPDATE` | 精修后答案更新 | `true` |

### 问题检测配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CC_QUESTION_CONFIDENCE_THRESHOLD` | 置信度阈值 | `0.7` |
| `CC_QUESTION_COOLDOWN_SECONDS` | 冷却间隔 | `15` |
| `CC_QUESTION_SIMILARITY_THRESHOLD` | 去重相似度阈值 | `0.8` |
| `CC_LLM_FILTER_MODE` | LLM 输入过滤 (teacher_only/all) | `teacher_only` |

### OSS 配置（可选，豆包离线用）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CC_OSS_ACCESS_KEY_ID` | OSS Access Key ID | — |
| `CC_OSS_ACCESS_KEY_SECRET` | OSS Access Key Secret | — |
| `CC_OSS_BUCKET_NAME` | OSS Bucket 名称 | — |
| `CC_OSS_ENDPOINT` | OSS Endpoint | `oss-cn-beijing.aliyuncs.com` |
| `CC_OSS_UPLOAD_PREFIX` | 上传路径前缀 | `class_copilot` |
| `CC_OSS_URL_EXPIRY_SECONDS` | 签名 URL 有效期 | `3600` |

</details>

## 日志

日志文件位于 `data/logs/`，按类别分文件并自动轮转：

| 日志文件 | 内容 | 保留 |
|---------|------|------|
| `app_{date}.log` | 全量日志 (DEBUG+) | 每日轮转 |
| `error_{date}.log` | 错误日志 (ERROR+) | 90 天 |
| `asr_{date}.log` | ASR 转写详情 | 14 天 |
| `llm_{date}.log` | 问题检测与答案生成 | 14 天 |
| `websocket_{date}.log` | WebSocket 事件 | 7 天 |

## 目录结构

```
class_copilot/
├── app.py                 # FastAPI 应用创建与生命周期管理
├── config.py              # Pydantic Settings 配置管理
├── database.py            # SQLAlchemy 异步数据库初始化
├── logger.py              # loguru 多文件日志配置
├── __main__.py            # 应用入口
├── frontend/              # 前端静态文件 (SPA)
│   ├── index.html
│   └── assets/
│       ├── app.js
│       └── style.css
├── models/
│   └── models.py          # SQLAlchemy ORM 模型
├── routes/
│   ├── api_routes.py      # REST API 路由
│   └── ws_routes.py       # WebSocket 路由
└── services/
    ├── asr_service.py             # DashScope 实时 ASR
    ├── doubao_asr_service.py      # 豆包实时 ASR
    ├── audio_service.py           # 音频采集与 MP3 编码
    ├── llm_service.py             # LLM 调用（问题检测 + 答案生成）
    ├── question_detector.py       # 问题检测调度与去重
    ├── refinement_service.py      # DashScope 精修服务
    ├── doubao_refinement_service.py # 豆包精修服务
    ├── session_manager.py         # 会话管理中枢
    ├── notification_service.py    # Windows 通知
    ├── hotkey_service.py          # 全局快捷键
    ├── tray_service.py            # 系统托盘
    ├── encryption_service.py      # Fernet 加密服务
    └── oss_service.py             # 阿里云 OSS 上传
```
