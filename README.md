# 听课助手 (Class Copilot)

> 实时听课辅助工具 — 课堂语音转写、问题检测与智能答案生成。

面向大学课堂场景的桌面端应用，基于 FastAPI + WebSocket 构建，支持实时语音识别、教师提问自动检测、AI 答案生成、高精度转写精修及完整的课堂记录归档。

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

### 配置 API 密钥

本项目依赖多个云服务 API。启动前需在项目根目录创建 `.env` 文件，或在应用内的「设置」页面中填写。

以下是一个最小可用的 `.env` 示例（使用阿里百炼作为 ASR + LLM）：

```env
CC_DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
CC_ASR_PROVIDER=dashscope
```

如需切换豆包 ASR 或启用 OSS，请参考下方的 [API 申请与配置指南](#api-申请与配置指南)。

---

## API 申请与配置指南

本项目涉及三类云服务：**阿里云百炼**（ASR + LLM）、**火山引擎豆包**（ASR）、**阿里云 OSS**（音频文件存储）。以下详细说明各服务的申请和配置流程。

### 1. 阿里云百炼（DashScope）—— ASR 语音转写 + LLM 大模型

阿里云百炼平台提供 ASR 语音识别和通义千问大模型服务，本项目默认使用百炼作为 ASR 和 LLM 引擎。**只需一个 API Key 即可同时使用 ASR 和 LLM 功能。**

#### 1.1 注册与开通

1. 访问 [阿里云百炼控制台](https://bailian.console.aliyun.com/)
2. 使用阿里云账号登录（如没有阿里云账号需先注册）
3. 首次进入会提示开通百炼服务，按照引导完成开通
4. 百炼提供新用户免费额度，包括 ASR 和 LLM 调用

#### 1.2 获取 API Key

1. 进入百炼控制台，点击右上角头像 → **API-KEY 管理**
2. 点击 **创建新的 API-KEY**
3. 选择作用范围（推荐「整个阿里云账号」）
4. 复制生成的 API Key（格式如 `sk-xxxxxxxxxxxxxxxxxxxxxxxx`）

> ⚠️ API Key 创建后仅显示一次，请立即保存。

#### 1.3 配置到项目

在 `.env` 文件中添加：

```env
CC_DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
CC_ASR_PROVIDER=dashscope
CC_REFINEMENT_PROVIDER=dashscope
```

或在应用启动后，进入 **设置页面** → 填写 **DashScope API Key** 字段。

#### 1.4 涉及的模型

| 用途 | 模型 | 说明 |
|------|------|------|
| 实时 ASR | `paraformer-realtime-v2` | 实时语音流转写 |
| 离线精修 ASR | `paraformer-v2` | 录音文件转写，精度更高 |
| LLM 问题检测 | `qwen-turbo-latest` | 快速判断疑问句 |
| LLM 简洁答案 | `qwen3.5-flash` | 2-3 句快速响应 |
| LLM 详细答案 | `qwen3.5-plus` | 5-8 句深度回答 |

#### 1.5 费用说明

- 百炼新用户通常有免费额度（ASR + LLM）
- ASR 按音频时长计费；LLM 按 Token 用量计费
- 详细价格参见 [百炼计费说明](https://help.aliyun.com/zh/model-studio/billing-overview)

---

### 2. 火山引擎豆包 —— Seed ASR 语音识别

豆包是火山引擎（字节跳动）推出的 AI 平台，其 Seed ASR 大模型在中文语音识别上表现优异。可作为 DashScope ASR 的替代方案。

#### 2.1 注册与开通

1. 访问 [火山引擎控制台](https://console.volcengine.com/)
2. 注册火山引擎账号并完成实名认证
3. 在控制台搜索「语音识别」或进入 **AI 应用** → **语音技术** → **语音识别**
4. 开通语音识别服务

#### 2.2 创建应用并获取凭证

1. 进入 **语音识别控制台**，点击 **应用管理** → **创建应用**
2. 填写应用名称（如 `class_copilot`），选择所需的语音识别服务
3. 创建完成后，记录以下信息：
   - **App ID**：应用唯一标识
4. 进入应用详情 → **Access Token 管理** → **创建 Token**
   - 复制生成的 **Access Token**

#### 2.3 确认 Resource ID

豆包 ASR 使用 Resource ID 区分不同的识别模式：

| Resource ID | 用途 | 说明 |
|-------------|------|------|
| `volc.seedasr.sauc.duration` | 实时流式识别 | 按时长计费版本，用于课堂实时转写 |
| `volc.seedasr.auc` | 录音文件识别 | 离线转写，用于精修 |

> 如果你在火山引擎控制台看到的 Resource ID 不同，请以控制台显示为准。

#### 2.4 配置到项目

在 `.env` 文件中添加：

```env
CC_ASR_PROVIDER=doubao
CC_DOUBAO_APPID=你的AppID
CC_DOUBAO_ACCESS_TOKEN=你的AccessToken
CC_DOUBAO_RESOURCE_ID_STREAMING=volc.seedasr.sauc.duration
CC_DOUBAO_RESOURCE_ID_OFFLINE=volc.seedasr.auc
```

如果仅精修使用豆包（实时仍用百炼）：

```env
CC_ASR_PROVIDER=dashscope
CC_REFINEMENT_PROVIDER=doubao
CC_DASHSCOPE_API_KEY=sk-xxxxxxxx
CC_DOUBAO_APPID=你的AppID
CC_DOUBAO_ACCESS_TOKEN=你的AccessToken
```

#### 2.5 费用说明

- 火山引擎新用户通常有免费试用额度
- ASR 按音频时长计费
- 详细价格参见 [火山引擎语音识别定价](https://www.volcengine.com/docs/6561/163043)

---

### 3. 阿里云 OSS —— 音频文件存储（可选）

阿里云 OSS（对象存储服务）用于存储课堂录音文件，生成公网可访问的签名 URL。**仅在使用豆包作为精修 ASR 引擎时需要**，因为豆包离线转写需要通过 URL 访问音频文件。

> 如果 ASR 和精修均使用 DashScope，则无需配置 OSS。

#### 3.1 开通 OSS 服务

1. 访问 [阿里云 OSS 控制台](https://oss.console.aliyun.com/)
2. 如未开通，点击 **立即开通**，按引导完成

#### 3.2 创建 Bucket

1. 在 OSS 控制台点击 **Bucket 列表** → **创建 Bucket**
2. 填写配置：
   - **Bucket 名称**：自定义，如 `class-copilot-audio`
   - **地域**：选择与你所在地最近的区域（如 `华北2（北京）`）
   - **存储类型**：标准存储
   - **读写权限**：**私有**（通过签名 URL 授权访问，更安全）
3. 点击确定创建

#### 3.3 获取 AccessKey

1. 访问 [AccessKey 管理页面](https://ram.console.aliyun.com/manage/ak)
2. 推荐使用 **RAM 子账号** 的 AccessKey（更安全）：
   - 进入 **RAM 访问控制** → **用户** → **创建用户**
   - 勾选 **OpenAPI 调用访问**
   - 创建完成后保存 **AccessKey ID** 和 **AccessKey Secret**
   - 给该用户添加权限：**AliyunOSSFullAccess**（或自定义更精细的权限策略）

> ⚠️ 切勿使用主账号 AccessKey，建议始终使用 RAM 子账号以降低安全风险。

#### 3.4 配置到项目

在 `.env` 文件中添加：

```env
CC_OSS_ACCESS_KEY_ID=LTAI5txxxxxxxxxxxxxx
CC_OSS_ACCESS_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
CC_OSS_BUCKET_NAME=class-copilot-audio
CC_OSS_ENDPOINT=oss-cn-beijing.aliyuncs.com
CC_OSS_UPLOAD_PREFIX=class_copilot
CC_OSS_URL_EXPIRY_SECONDS=3600
```

**参数说明**：

| 参数 | 说明 |
|------|------|
| `CC_OSS_ENDPOINT` | Bucket 所在地域的外网 Endpoint。在 Bucket 概览页可查看，格式为 `oss-cn-{region}.aliyuncs.com` |
| `CC_OSS_UPLOAD_PREFIX` | 文件上传到 Bucket 中的目录前缀，默认 `class_copilot` |
| `CC_OSS_URL_EXPIRY_SECONDS` | 签名 URL 有效期（秒），默认 3600（1 小时），需大于音频文件的转写处理时间 |

#### 3.5 费用说明

- OSS 按存储量 + 请求次数 + 流量计费
- 课堂录音通常体积较小（90 分钟约 50-80 MB MP3），费用极低
- 详细价格参见 [OSS 定价](https://www.aliyun.com/price/product#/oss/detail)

---

### 配置方式汇总

项目支持两种配置方式，优先级：应用内设置 > `.env` 文件。

**方式一：`.env` 文件**（推荐初始配置时使用）

在项目根目录创建 `.env` 文件，所有变量以 `CC_` 为前缀。

**方式二：应用内设置**

启动应用后，在浏览器界面点击 **⚙️ 设置** 标签页，可视化填写所有 API 密钥和配置项。敏感字段（API Key 等）会以 Fernet 加密存储在数据库中。

---

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

## 完整配置项参考

<details>
<summary>点击展开完整配置项列表</summary>

所有配置项均可通过 `.env` 文件设置，变量前缀为 `CC_`。

### ASR 配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CC_ASR_PROVIDER` | 实时 ASR 引擎 (`dashscope` / `doubao`) | `dashscope` |
| `CC_REFINEMENT_PROVIDER` | 精修 ASR 引擎 (`dashscope` / `doubao`) | `dashscope` |
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
| `CC_REFINEMENT_STRATEGY` | 精修策略 (`post` / `periodic` / `manual`) | `post` |
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
| `CC_LLM_FILTER_MODE` | LLM 输入过滤 (`teacher_only` / `all`) | `teacher_only` |

### OSS 配置（可选）

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
