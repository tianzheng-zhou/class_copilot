# 听课助手（class_copilot）— 前端技术方案 & 数据库设计

> 版本：v1.0
> 日期：2026-03-20

---

## 1. 前端技术选型

### 1.1 方案对比

| 方案 | 优点 | 缺点 | 适合度 |
|------|------|------|--------|
| **纯 HTML/CSS/JS** | 零构建、零依赖、FastAPI 直接 serve | 状态管理混乱、组件复用差、开发效率低、Markdown 渲染需手动集成 | ⭐⭐ |
| **Vue 3 + Vite** | 响应式数据绑定、组件化、生态成熟、构建后仍是静态文件 | 需构建步骤 | ⭐⭐⭐⭐⭐ |
| **React + Vite** | 生态最大、社区资源丰富 | JSX 心智负担、本项目无需服务端渲染 | ⭐⭐⭐⭐ |
| **Svelte** | 编译时框架、包小 | 生态较小、第三方组件少 | ⭐⭐⭐ |

### 1.2 最终选型：Vue 3 + Vite + TypeScript

**理由：**

1. **响应式天然匹配**：Vue 3 的 `ref`/`reactive` 完美适配实时转写、答案流式更新等场景——数据变，视图自动变
2. **组件化**：转写区域、答案卡片、提问对话、设置面板均可封装为独立组件，复用性强
3. **Composition API**：WebSocket 连接、音频状态、会话管理等可抽取为 composable（`useWebSocket`、`useSession`），逻辑清晰
4. **构建产物就是静态文件**：`vite build` 产出 `dist/`，FastAPI 用 `StaticFiles` 直接 serve，无需 Node 运行时
5. **TypeScript 加持**：WebSocket 消息类型、API 响应类型有完整类型安全，减少运行时错误
6. **开发体验**：Vite HMR 热更新毫秒级，开发阶段可代理 API 到 FastAPI 后端
7. **轻量**：最终打包产物 gzip 后约 100-200KB（含依赖），加载速度快

### 1.3 前端依赖清单

| 包名 | 用途 | 版本要求 |
|------|------|---------|
| `vue` | UI 框架 | ^3.5 |
| `vue-router` | 路由（选项卡切换 / 设置页面） | ^4.4 |
| `pinia` | 状态管理（会话、转写、设置等全局状态） | ^2.2 |
| `marked` | Markdown → HTML 渲染 | ^15.0 |
| `highlight.js` | 代码块语法高亮（配合 marked） | ^11.10 |
| `DOMPurify` | HTML 消毒（防 XSS，sanitize marked 输出） | ^3.2 |

**不需要的：**
- 不需要 Axios（用原生 `fetch` 调 REST API 足够，WebSocket 是主通道）
- 不需要 UI 组件库（自定义深色主题，组件库反而增加包体积和定制成本）
- 不需要 CSS 框架（手写 CSS/SCSS，完全控制深色主题）

### 1.4 开发 / 生产双模式

```
开发模式：
  Vite dev server (localhost:5173) → 代理 API/WS → FastAPI (localhost:8000)

生产模式：
  vite build → dist/ → FastAPI StaticFiles serve (localhost:8000)
```

Vite 开发代理配置：

```typescript
// vite.config.ts
export default defineConfig({
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
})
```

---

## 2. 前端目录结构

```
frontend/
├── index.html                          # Vite 入口 HTML
├── vite.config.ts                      # Vite 配置（代理、构建输出）
├── tsconfig.json                       # TypeScript 配置
├── package.json                        # 依赖 & 脚本
│
├── public/                             # 静态资源（直接拷贝到 dist/）
│   └── favicon.ico                     # 浏览器图标（伪装用，选普通图标）
│
├── src/
│   ├── main.ts                         # 应用入口（创建 app、挂载插件）
│   ├── App.vue                         # 根组件（布局骨架）
│   │
│   ├── types/                          # TypeScript 类型定义
│   │   ├── ws-messages.ts              # WebSocket 消息类型（与后端 protocol.py 对应）
│   │   ├── api.ts                      # REST API 请求/响应类型
│   │   └── models.ts                   # 业务实体类型（Session, Transcript 等）
│   │
│   ├── composables/                    # Composition API 可复用逻辑
│   │   ├── useWebSocket.ts             # WebSocket 连接管理（连接/断线重连/消息分发）
│   │   ├── useSession.ts              # 会话状态管理（开始/停止/续记）
│   │   ├── useAudio.ts                # 音频状态（录音中/已停止/设备列表）
│   │   ├── useNotification.ts         # 页面内 Toast 通知
│   │   └── useClipboard.ts            # 复制到剪贴板
│   │
│   ├── stores/                         # Pinia 状态仓库
│   │   ├── session.ts                  # 当前会话状态
│   │   ├── transcript.ts              # 转写片段列表（中间结果 + 最终结果）
│   │   ├── questions.ts               # 检测到的问题 & 答案列表
│   │   ├── chat.ts                    # 主动提问对话消息列表
│   │   ├── history.ts                 # 历史会话列表
│   │   ├── settings.ts               # 用户设置（本地缓存 + 后端同步）
│   │   └── ui.ts                      # UI 状态（当前选项卡、面板开关等）
│   │
│   ├── views/                          # 页面级视图（对应选项卡）
│   │   ├── TranscriptView.vue         # 转写选项卡
│   │   ├── AnswersView.vue            # 回答选项卡
│   │   ├── AskView.vue                # 提问选项卡
│   │   └── HistoryView.vue            # 历史选项卡
│   │
│   ├── components/                     # 可复用组件
│   │   ├── layout/                     # 布局组件
│   │   │   ├── TopNavBar.vue           # 顶部导航栏（课程名、录音按钮、状态）
│   │   │   ├── StatusBar.vue           # 状态栏（连接状态、精修进度、Toast）
│   │   │   ├── TabBar.vue              # 选项卡切换栏
│   │   │   └── BottomActionBar.vue     # 底部操作栏（快捷按钮）
│   │   │
│   │   ├── transcript/                 # 转写相关组件
│   │   │   ├── TranscriptLine.vue      # 单行转写（说话人标签 + 文本 + 精修角标）
│   │   │   └── TranscriptScroller.vue  # 自动滚动容器
│   │   │
│   │   ├── answer/                     # 答案相关组件
│   │   │   ├── QuestionCard.vue        # 问题+答案卡片（简洁/展开切换）
│   │   │   └── AnswerContent.vue       # 答案内容区（流式文本 / 加载态）
│   │   │
│   │   ├── chat/                       # 主动提问相关组件
│   │   │   ├── ChatMessage.vue         # 单条消息（用户/AI）
│   │   │   ├── ChatInput.vue           # 输入框（回车提交 + 模型选择）
│   │   │   └── MarkdownRenderer.vue    # Markdown 渲染（代码高亮 + XSS 消毒）
│   │   │
│   │   ├── history/                    # 历史相关组件
│   │   │   ├── SessionList.vue         # 会话列表
│   │   │   └── SessionDetail.vue       # 会话详情（转写 + 问答回顾）
│   │   │
│   │   ├── settings/                   # 设置面板组件
│   │   │   ├── SettingsModal.vue       # 设置模态框容器
│   │   │   ├── ApiKeySection.vue       # API 密钥设置
│   │   │   ├── AudioSection.vue        # 音频设置
│   │   │   ├── RefineSection.vue       # 精修设置
│   │   │   └── GeneralSection.vue      # 通用设置
│   │   │
│   │   └── common/                     # 通用组件
│   │       ├── IconButton.vue          # 图标按钮
│   │       ├── Toast.vue               # Toast 通知
│   │       ├── ConfirmDialog.vue       # 确认对话框
│   │       └── LoadingSpinner.vue      # 加载动画
│   │
│   ├── router/                         # 路由配置
│   │   └── index.ts                    # 选项卡路由定义
│   │
│   ├── styles/                         # 全局样式
│   │   ├── variables.css               # CSS 变量（颜色、间距、字号等）
│   │   ├── base.css                    # 基础样式（reset、全局字体）
│   │   └── transitions.css             # 过渡动画（精修文本淡入等）
│   │
│   └── utils/                          # 工具函数
│       ├── api.ts                      # REST API 封装（fetch wrapper）
│       ├── format.ts                   # 格式化工具（时间戳、时长等）
│       └── markdown.ts                 # Markdown 渲染管线（marked + highlight.js + DOMPurify）
│
└── dist/                               # 构建产物（gitignore，部署时生成）
    ├── index.html
    └── assets/
        ├── index-[hash].js
        └── index-[hash].css
```

---

## 3. 前端与后端通信协议

### 3.1 通信架构

```
┌─────────────────────────────────────────────┐
│                  浏览器前端                    │
│                                             │
│   WebSocket (ws://localhost:8000/ws)        │  ← 实时双向通信（主通道）
│   REST API  (http://localhost:8000/api/*)   │  ← CRUD 操作（补充）
└─────────────────────────────────────────────┘
```

**分工原则：**

| 通道 | 用途 |
|------|------|
| **WebSocket** | 所有实时推送（转写、问题、答案流式、精修状态）+ 客户端指令（开始/停止、提问） |
| **REST API** | 非实时操作（历史查询、设置读写、声纹管理、会话 CRUD、导出、删除、音频设备列表） |

### 3.2 WebSocket 消息总协议

所有消息统一为 JSON 格式，必含 `type` 字段：

```typescript
interface WSMessage {
  type: string          // 消息类型标识
  data: object          // 消息载荷
  ts?: number           // 服务端时间戳（Unix ms），仅 Server→Client
  msg_id?: string       // 消息唯一 ID（用于断线重连补发）
}
```

### 3.3 Server → Client 消息类型

#### 3.3.1 `transcript` — 转写片段

```typescript
{
  type: "transcript",
  data: {
    segment_id: string,         // 片段唯一 ID
    session_id: string,         // 所属会话 ID
    text: string,               // 转写文本
    is_final: boolean,          // true=最终结果, false=中间结果
    speaker_label: string,      // 说话人标签 ("speaker_0", "speaker_1" 等)
    speaker_role: string | null,// 说话人角色 ("teacher" | "student" | null)
    start_time: number,         // 音频起始时间（秒，相对于录音开始）
    end_time: number,           // 音频结束时间（秒）
    language: string,           // 识别语言 ("zh" | "en" | "mixed")
  },
  ts: 1711000000000,
  msg_id: "msg_xxxxx"
}
```

**前端处理逻辑：**
- `is_final=false`：更新（或插入）`segment_id` 对应的行，灰色样式
- `is_final=true`：替换 `segment_id` 对应的中间结果，白色样式，持久化
- 根据 `speaker_role` 选择颜色（teacher=蓝色系，student=绿色系，null=默认白色）

#### 3.3.2 `transcript_translation` — 转写翻译

```typescript
{
  type: "transcript_translation",
  data: {
    segment_id: string,         // 对应的转写片段 ID
    translation: string,        // 翻译文本
    source_language: string,    // 原文语言
    target_language: string,    // 目标语言
  },
  ts: 1711000000000
}
```

#### 3.3.3 `refine_update` — 精修文本替换

```typescript
{
  type: "refine_update",
  data: {
    segment_id: string,         // 被替换的片段 ID
    refined_text: string,       // 精修后文本
    refined_speaker_label: string,
    refined_speaker_role: string | null,
  },
  ts: 1711000000000
}
```

**前端处理：** 找到对应 `segment_id` 的转写行，0.3s 淡入动画替换文本，显示 ✓ 角标。

#### 3.3.4 `question_detected` — 检测到问题

```typescript
{
  type: "question_detected",
  data: {
    question_id: string,        // 问题唯一 ID
    session_id: string,
    question_text: string,      // 问题文本
    source: "auto" | "manual" | "refined",  // 检测来源
    confidence: number,         // 置信度 0~1
    context_snippet: string,    // 上下文摘要（用于卡片展示）
    detected_at: number,        // 检测时间（Unix ms）
  },
  ts: 1711000000000,
  msg_id: "msg_xxxxx"
}
```

**前端处理：** 在"回答"选项卡插入新问题卡片，显示来源图标（🔍/✋/🔄），答案区域显示"正在生成答案…"。

#### 3.3.5 `answer_chunk` — 答案流式片段

```typescript
{
  type: "answer_chunk",
  data: {
    question_id: string,        // 关联的问题 ID
    answer_type: "brief" | "detailed",  // 简洁版 / 展开版
    chunk: string,              // 文本增量
    is_done: boolean,           // 是否最后一块
  },
  ts: 1711000000000
}
```

**前端处理：** 追加 `chunk` 到对应问题卡片的答案区域。`is_done=true` 时移除"生成中"状态。简洁版和展开版并行流式到达，前端按当前显示模式决定展示哪个。

#### 3.3.6 `answer_complete` — 答案生成完成

```typescript
{
  type: "answer_complete",
  data: {
    question_id: string,
    answer_type: "brief" | "detailed",
    full_text: string,          // 完整答案文本（用于校验/持久化）
    answer_id: string,          // 答案记录 ID
  },
  ts: 1711000000000,
  msg_id: "msg_xxxxx"
}
```

#### 3.3.7 `answer_updated` — 精修后答案更新

```typescript
{
  type: "answer_updated",
  data: {
    question_id: string,
    answer_type: "brief" | "detailed",
    full_text: string,          // 更新后的完整答案
    answer_id: string,
    reason: "refined",          // 更新原因
  },
  ts: 1711000000000
}
```

#### 3.3.8 `active_qa_chunk` — 主动提问回答流式片段

```typescript
{
  type: "active_qa_chunk",
  data: {
    chat_id: string,            // 对话消息 ID
    chunk: string,              // 文本增量
    is_done: boolean,
  },
  ts: 1711000000000
}
```

#### 3.3.9 `active_qa_complete` — 主动提问回答完成

```typescript
{
  type: "active_qa_complete",
  data: {
    chat_id: string,
    full_text: string,
    model_used: string,         // 实际使用的模型名
  },
  ts: 1711000000000,
  msg_id: "msg_xxxxx"
}
```

#### 3.3.10 `refine_status` — 精修状态更新

```typescript
{
  type: "refine_status",
  data: {
    session_id: string,
    status: "idle" | "running" | "completed" | "partial" | "failed" | "paused",
    progress: number,           // 0~100 百分比
    current_segment: number,    // 当前处理到第几段
    total_segments: number,     // 总段数
    message: string | null,     // 附加信息（如错误原因）
  },
  ts: 1711000000000
}
```

#### 3.3.11 `speaker_identified` — 说话人身份识别

```typescript
{
  type: "speaker_identified",
  data: {
    speaker_label: string,      // "speaker_0"
    speaker_role: string,       // "teacher"
    speaker_name: string | null,// "张教授"（声纹匹配到时）
    method: "voiceprint" | "manual",  // 识别方式
  },
  ts: 1711000000000
}
```

#### 3.3.12 `status` — 系统状态变更

```typescript
{
  type: "status",
  data: {
    category: "asr" | "recording" | "connection" | "system",
    state: string,              // 如 "listening", "stopped", "reconnecting", "error"
    message: string,            // 可读描述
  },
  ts: 1711000000000
}
```

#### 3.3.13 `error` — 错误通知

```typescript
{
  type: "error",
  data: {
    code: string,               // 错误码（如 "ASR_DISCONNECTED", "LLM_QUOTA_EXCEEDED"）
    message: string,            // 可读错误信息
    severity: "warning" | "error" | "fatal",
    recoverable: boolean,       // 是否可自动恢复
  },
  ts: 1711000000000
}
```

### 3.4 Client → Server 消息类型

#### 3.4.1 `command` — 控制指令

```typescript
{
  type: "command",
  data: {
    action: "start_listening"       // 开始录音+转写
          | "stop_listening"        // 停止录音+转写
          | "manual_detect"         // 手动触发问题检测
          | "force_answer"          // 强制生成答案（无论是否检测到问题）
          | "toggle_filter_mode"    // 切换 LLM 输入模式（仅教师/全部）
          | "manual_refine"         // 手动触发精修
          | "copy_transcript"       // 请求复制当前转写
          | "mark_speaker",         // 标记说话人为教师
    params: object | null           // 指令参数
  }
}
```

**指令参数详解：**

```typescript
// start_listening
{ action: "start_listening", params: { session_id?: string } }
// session_id 为空时新建会话，有值时续记

// stop_listening
{ action: "stop_listening", params: null }

// manual_detect
{ action: "manual_detect", params: null }

// force_answer — 手动选中一段文本强制生成答案
{ action: "force_answer", params: { context_text: string } }

// manual_refine
{ action: "manual_refine", params: { scope: "all" | "recent", minutes?: number } }

// mark_speaker — 标记某个说话人为教师
{ action: "mark_speaker", params: { speaker_label: "speaker_0", role: "teacher" } }
```

#### 3.4.2 `active_question` — 主动提问

```typescript
{
  type: "active_question",
  data: {
    question: string,               // 用户问题文本
    model_preference: "fast" | "quality" | "thinking",  // 模型偏好
    session_id: string,             // 当前会话 ID（用于获取上下文）
  }
}
```

#### 3.4.3 `heartbeat` — 心跳

```typescript
{
  type: "heartbeat",
  data: {}
}
```

### 3.5 REST API 端点设计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sessions` | 获取历史会话列表（分页） |
| GET | `/api/sessions/{id}` | 获取会话详情 |
| DELETE | `/api/sessions/{id}` | 删除会话（含录音、转写、问答） |
| GET | `/api/sessions/{id}/transcripts` | 获取会话完整转写 |
| GET | `/api/sessions/{id}/questions` | 获取会话问题列表 |
| GET | `/api/sessions/{id}/chat-messages` | 获取会话主动提问记录 |
| GET | `/api/sessions/{id}/export` | 导出会话为 Markdown |
| GET | `/api/settings` | 获取当前设置 |
| PUT | `/api/settings` | 更新设置 |
| GET | `/api/audio-devices` | 获取可用麦克风设备列表 |
| GET | `/api/courses` | 获取课程列表（含热词） |
| POST | `/api/courses` | 创建课程 |
| PUT | `/api/courses/{id}` | 更新课程（热词等） |
| GET | `/api/voiceprints` | 获取声纹列表 |
| DELETE | `/api/voiceprints/{id}` | 删除声纹 |
| GET | `/api/refine/usage` | 获取精修用量统计 |

### 3.6 断线重连协议

```
前端连接 WebSocket:
  ws://localhost:8000/ws?last_msg_id=<最后收到的 msg_id>

服务端行为：
  1. 如果 last_msg_id 存在，从消息缓冲区中找到该 ID 之后的消息
  2. 按序推送缺失的消息
  3. 推送 { type: "status", data: { category: "connection", state: "synced" } }
  4. 恢复正常推送

前端重连策略：
  断线 → 1s → 重试 → 失败 → 2s → 重试 → 失败 → 4s → ... → 上限 30s
  状态栏显示"连接断开，正在重连..."
  成功重连后状态栏显示"已重连"并在 3s 后消失
```

---

## 4. SQLite 数据库完整表设计

### 4.1 设计原则

- **UUID 主键**：所有表使用 UUID v4 字符串主键（`TEXT`），避免自增 ID 在续记/合并时冲突
- **时间戳**：统一使用 ISO 8601 格式字符串（`TEXT`），SQLite 原生支持比较和排序
- **软删除**：不使用软删除，直接物理删除（单用户本地应用，无需审计）
- **WAL 模式**：启用 WAL 以支持并发读写
- **外键约束**：启用 `PRAGMA foreign_keys = ON`

### 4.2 初始化 PRAGMA

```sql
-- 每次连接时执行
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;  -- 64MB 缓存
```

### 4.3 courses — 课程信息

```sql
CREATE TABLE courses (
    id          TEXT PRIMARY KEY,                           -- UUID
    name        TEXT NOT NULL UNIQUE,                       -- 课程名称，如"马克思主义基本原理"
    language    TEXT NOT NULL DEFAULT 'zh',                 -- 授课语言: zh / en / mixed
    hotwords    TEXT DEFAULT NULL,                          -- 课程热词，逗号分隔，如"唯物辩证法,形而上学"
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_courses_name ON courses(name);
```

### 4.4 sessions — 课堂会话

```sql
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,                       -- UUID
    course_id       TEXT DEFAULT NULL,                      -- 关联课程（可为空，不强制）
    course_name     TEXT NOT NULL,                          -- 冗余存储课程名（快速展示）
    status          TEXT NOT NULL DEFAULT 'created',        -- created / listening / stopped / error
    started_at      TEXT DEFAULT NULL,                      -- 开始监听时间
    stopped_at      TEXT DEFAULT NULL,                      -- 停止监听时间

    -- 精修相关
    refine_status   TEXT NOT NULL DEFAULT 'none',           -- none / pending / running / completed / partial / failed
    refine_progress INTEGER NOT NULL DEFAULT 0,             -- 精修进度百分比 0~100
    refine_strategy TEXT DEFAULT NULL,                      -- post_class / in_class / manual / null

    -- 续记相关
    parent_session_id TEXT DEFAULT NULL,                    -- 续记时的前一个会话（用于串联），通常为 null

    -- 统计
    total_duration  REAL DEFAULT 0,                         -- 累计录音时长（秒），含多段录音
    segment_count   INTEGER NOT NULL DEFAULT 0,             -- 转写片段数

    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE SET NULL
);

CREATE INDEX idx_sessions_created_at ON sessions(created_at DESC);
CREATE INDEX idx_sessions_course_name ON sessions(course_name);
CREATE INDEX idx_sessions_status ON sessions(status);
```

### 4.5 recordings — 录音文件

```sql
CREATE TABLE recordings (
    id              TEXT PRIMARY KEY,                       -- UUID
    session_id      TEXT NOT NULL,                          -- 所属会话
    file_path       TEXT NOT NULL,                          -- 录音文件相对路径（相对于 data/recordings/）
    file_size       INTEGER DEFAULT 0,                      -- 文件大小（字节）
    duration        REAL DEFAULT 0,                         -- 录音时长（秒）
    sample_rate     INTEGER NOT NULL DEFAULT 16000,         -- 采样率
    format          TEXT NOT NULL DEFAULT 'mp3',            -- 音频格式
    sequence_num    INTEGER NOT NULL DEFAULT 1,             -- 本次会话中的录音序号（续记时递增）

    -- 精修相关
    refine_status   TEXT NOT NULL DEFAULT 'none',           -- none / pending / submitted / completed / failed
    refine_task_id  TEXT DEFAULT NULL,                      -- 关联的精修任务 ID（DashScope 返回的 task_id）

    started_at      TEXT NOT NULL,                          -- 录音开始时间
    stopped_at      TEXT DEFAULT NULL,                      -- 录音结束时间
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX idx_recordings_session_id ON recordings(session_id);
```

### 4.6 transcriptions — 转写片段

```sql
CREATE TABLE transcriptions (
    id                  TEXT PRIMARY KEY,                   -- UUID（即 segment_id）
    session_id          TEXT NOT NULL,                      -- 所属会话
    recording_id        TEXT DEFAULT NULL,                  -- 关联录音文件（可为空，中间结果可能还未关联）

    -- 实时转写内容
    realtime_text       TEXT NOT NULL DEFAULT '',           -- 实时 ASR 文本（始终保留）
    is_final            INTEGER NOT NULL DEFAULT 0,         -- 0=中间结果, 1=最终结果

    -- 精修内容
    refined_text        TEXT DEFAULT NULL,                  -- 精修后文本（null 表示未精修）
    refine_status       TEXT NOT NULL DEFAULT 'none',       -- none / pending / completed / failed

    -- 说话人信息
    speaker_label       TEXT DEFAULT NULL,                  -- 实时 ASR 的说话人标签（"speaker_0" 等）
    speaker_role        TEXT DEFAULT NULL,                  -- 角色标注 (teacher / student / null)
    refined_speaker_label TEXT DEFAULT NULL,                -- 精修后的说话人标签
    refined_speaker_role  TEXT DEFAULT NULL,                -- 精修后的角色标注

    -- 时间信息（相对于录音开始的秒数）
    start_time          REAL NOT NULL DEFAULT 0,            -- 片段起始时间
    end_time            REAL NOT NULL DEFAULT 0,            -- 片段结束时间

    -- 元数据
    language            TEXT DEFAULT 'zh',                  -- 识别语言 (zh / en / mixed)
    translation         TEXT DEFAULT NULL,                  -- 翻译文本（英文→中文 或 中文→英文）
    sequence_num        INTEGER NOT NULL DEFAULT 0,         -- 在会话中的顺序号

    refined_at          TEXT DEFAULT NULL,                  -- 精修完成时间
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE SET NULL
);

CREATE INDEX idx_transcriptions_session_id ON transcriptions(session_id);
CREATE INDEX idx_transcriptions_session_seq ON transcriptions(session_id, sequence_num);
CREATE INDEX idx_transcriptions_recording_id ON transcriptions(recording_id);
CREATE INDEX idx_transcriptions_start_time ON transcriptions(session_id, start_time);
```

### 4.7 questions — 问题检测

```sql
CREATE TABLE questions (
    id              TEXT PRIMARY KEY,                       -- UUID
    session_id      TEXT NOT NULL,                          -- 所属会话
    question_text   TEXT NOT NULL,                          -- 检测到的问题文本
    context_snippet TEXT DEFAULT NULL,                      -- 触发问题的上下文摘要

    -- 检测信息
    source          TEXT NOT NULL DEFAULT 'auto',           -- auto / manual / force / refined
    confidence      REAL DEFAULT NULL,                      -- 置信度 0~1（手动/强制触发时为 null）

    -- 关联的转写片段范围
    start_segment_id TEXT DEFAULT NULL,                     -- 触发上下文起始片段 ID
    end_segment_id   TEXT DEFAULT NULL,                     -- 触发上下文结束片段 ID

    -- 答案状态
    brief_answer_status    TEXT NOT NULL DEFAULT 'pending', -- pending / generating / completed / error / disabled
    detailed_answer_status TEXT NOT NULL DEFAULT 'pending', -- pending / generating / completed / error / disabled

    -- 精修相关
    original_question_text TEXT DEFAULT NULL,               -- 精修前的问题文本（精修后补检更新时保留原文）
    is_refined_update      INTEGER NOT NULL DEFAULT 0,      -- 是否因精修而更新过

    detected_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX idx_questions_session_id ON questions(session_id);
CREATE INDEX idx_questions_detected_at ON questions(session_id, detected_at DESC);
CREATE INDEX idx_questions_source ON questions(source);
```

### 4.8 answers — 答案

```sql
CREATE TABLE answers (
    id              TEXT PRIMARY KEY,                       -- UUID
    question_id     TEXT NOT NULL,                          -- 关联的问题 ID
    session_id      TEXT NOT NULL,                          -- 冗余关联会话（加速查询）

    answer_type     TEXT NOT NULL,                          -- brief / detailed
    content         TEXT NOT NULL DEFAULT '',               -- 答案文本内容

    -- 状态
    status          TEXT NOT NULL DEFAULT 'generating',     -- generating / completed / error
    model_used      TEXT DEFAULT NULL,                      -- 使用的模型名称

    -- 精修更新
    is_refined_update INTEGER NOT NULL DEFAULT 0,           -- 是否因精修文本而重新生成
    original_content  TEXT DEFAULT NULL,                    -- 精修更新前的原始答案（保留对比）

    generated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX idx_answers_question_id ON answers(question_id);
CREATE INDEX idx_answers_session_id ON answers(session_id);
CREATE UNIQUE INDEX idx_answers_question_type ON answers(question_id, answer_type);
```

### 4.9 chat_messages — 主动提问记录

```sql
CREATE TABLE chat_messages (
    id              TEXT PRIMARY KEY,                       -- UUID
    session_id      TEXT NOT NULL,                          -- 所属会话
    role            TEXT NOT NULL,                          -- user / assistant
    content         TEXT NOT NULL DEFAULT '',               -- 消息内容

    -- 仅 assistant 消息有以下字段
    model_used      TEXT DEFAULT NULL,                      -- 使用的模型名称
    model_preference TEXT DEFAULT NULL,                     -- fast / quality / thinking

    -- 状态
    status          TEXT NOT NULL DEFAULT 'completed',      -- generating / completed / error（仅 assistant 有非 completed）

    -- 排序
    sequence_num    INTEGER NOT NULL DEFAULT 0,             -- 对话中的顺序号

    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX idx_chat_messages_session_seq ON chat_messages(session_id, sequence_num);
```

### 4.10 voiceprints — 声纹档案

```sql
CREATE TABLE voiceprints (
    id              TEXT PRIMARY KEY,                       -- UUID
    course_id       TEXT DEFAULT NULL,                      -- 关联课程（可选）
    course_name     TEXT NOT NULL,                          -- 冗余课程名
    speaker_name    TEXT NOT NULL,                          -- 说话人名称，如 "张教授"
    speaker_role    TEXT NOT NULL DEFAULT 'teacher',        -- teacher / other

    -- 声纹特征
    voiceprint_ref  TEXT NOT NULL,                          -- 云端声纹特征引用 ID / URL
    feature_hash    TEXT DEFAULT NULL,                      -- 声纹特征摘要 hash（用于判断是否需要更新）

    -- 管理
    is_active       INTEGER NOT NULL DEFAULT 1,             -- 是否启用
    match_count     INTEGER NOT NULL DEFAULT 0,             -- 累计匹配次数

    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE SET NULL
);

CREATE INDEX idx_voiceprints_course_id ON voiceprints(course_id);
CREATE INDEX idx_voiceprints_active ON voiceprints(is_active);
```

### 4.11 settings — 用户设置

```sql
CREATE TABLE settings (
    key         TEXT PRIMARY KEY,                           -- 设置项键名
    value       TEXT NOT NULL,                              -- 设置值（JSON 字符串或加密字符串）
    encrypted   INTEGER NOT NULL DEFAULT 0,                 -- 0=明文, 1=Fernet 加密
    category    TEXT NOT NULL DEFAULT 'general',            -- api_key / audio / refine / general
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
```

**预置设置项：**

```sql
-- API 密钥（加密存储）
INSERT INTO settings (key, value, encrypted, category) VALUES
    ('dashscope_api_key', '', 1, 'api_key');

-- 音频设置
INSERT INTO settings (key, value, encrypted, category) VALUES
    ('audio_device_id',    '"default"',  0, 'audio'),
    ('asr_model',          '"paraformer-realtime-v2"', 0, 'audio'),
    ('hotwords',           '""',         0, 'audio');

-- 精修设置
INSERT INTO settings (key, value, encrypted, category) VALUES
    ('refine_enabled',          'false',  0, 'refine'),
    ('refine_strategy',         '"post_class"', 0, 'refine'),
    ('refine_interval_minutes', '5',      0, 'refine'),
    ('refine_max_minutes',      '90',     0, 'refine'),
    ('refine_redetect_enabled', 'true',   0, 'refine'),
    ('refine_reanswer_enabled', 'true',   0, 'refine');

-- 通用设置
INSERT INTO settings (key, value, encrypted, category) VALUES
    ('language',             '"zh"',   0, 'general'),
    ('brief_answer_enabled', 'true',   0, 'general'),
    ('detailed_answer_enabled', 'true', 0, 'general'),
    ('translation_enabled',  'false',  0, 'general'),
    ('bilingual_enabled',    'false',  0, 'general'),
    ('data_storage_path',    '"data"', 0, 'general'),
    ('tab_title',            '"在线文档 - 编辑中"', 0, 'general');
```

### 4.12 refinement_tasks — 精修任务队列

```sql
CREATE TABLE refinement_tasks (
    id              TEXT PRIMARY KEY,                       -- UUID
    session_id      TEXT NOT NULL,                          -- 关联会话
    recording_id    TEXT NOT NULL,                          -- 关联录音文件

    -- 任务信息
    status          TEXT NOT NULL DEFAULT 'pending',        -- pending / submitted / processing / completed / failed / cancelled
    priority        INTEGER NOT NULL DEFAULT 0,             -- 优先级（越大越高）
    strategy        TEXT NOT NULL DEFAULT 'post_class',     -- post_class / in_class / manual

    -- DashScope 任务追踪
    remote_task_id  TEXT DEFAULT NULL,                      -- DashScope 返回的 task_id
    audio_url       TEXT DEFAULT NULL,                      -- 提交给 DashScope 的音频 URL/路径

    -- 进度
    progress        INTEGER NOT NULL DEFAULT 0,             -- 0~100
    segments_total  INTEGER NOT NULL DEFAULT 0,             -- 总片段数
    segments_done   INTEGER NOT NULL DEFAULT 0,             -- 已完成片段数

    -- 重试
    retry_count     INTEGER NOT NULL DEFAULT 0,             -- 已重试次数
    max_retries     INTEGER NOT NULL DEFAULT 3,             -- 最大重试次数
    last_error      TEXT DEFAULT NULL,                      -- 最近一次错误信息

    -- 时间范围（该录音中要精修的时间段，秒）
    time_range_start REAL DEFAULT NULL,                     -- 精修起始时间（null 表示全部）
    time_range_end   REAL DEFAULT NULL,                     -- 精修结束时间（null 表示全部）

    submitted_at    TEXT DEFAULT NULL,                      -- 提交时间
    completed_at    TEXT DEFAULT NULL,                      -- 完成时间
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
);

CREATE INDEX idx_refinement_tasks_session_id ON refinement_tasks(session_id);
CREATE INDEX idx_refinement_tasks_status ON refinement_tasks(status);
CREATE INDEX idx_refinement_tasks_priority ON refinement_tasks(status, priority DESC);
```

### 4.13 ER 关系图

```
courses 1──0..N sessions
sessions 1──1..N recordings
sessions 1──0..N transcriptions
sessions 1──0..N questions
sessions 1──0..N chat_messages
sessions 1──0..N refinement_tasks
recordings 1──0..N transcriptions
recordings 1──0..N refinement_tasks
questions 1──0..2 answers (brief + detailed)
courses 1──0..N voiceprints
settings (独立键值表，无外键)
```

---

## 5. 关键前端实现要点

### 5.1 WebSocket 连接管理（composable 骨架）

```typescript
// src/composables/useWebSocket.ts
import { ref, onUnmounted } from 'vue'

export function useWebSocket() {
  const connected = ref(false)
  const lastMsgId = ref<string | null>(null)
  let ws: WebSocket | null = null
  let reconnectTimer: number | null = null
  let reconnectDelay = 1000

  function connect() {
    const params = lastMsgId.value ? `?last_msg_id=${lastMsgId.value}` : ''
    ws = new WebSocket(`ws://${location.host}/ws${params}`)

    ws.onopen = () => {
      connected.value = true
      reconnectDelay = 1000 // 重置退避
    }

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      if (msg.msg_id) lastMsgId.value = msg.msg_id
      dispatch(msg)
    }

    ws.onclose = () => {
      connected.value = false
      scheduleReconnect()
    }
  }

  function scheduleReconnect() {
    reconnectTimer = window.setTimeout(() => {
      reconnectDelay = Math.min(reconnectDelay * 2, 30000)
      connect()
    }, reconnectDelay)
  }

  function send(msg: object) {
    ws?.send(JSON.stringify(msg))
  }

  function dispatch(msg: { type: string; data: any }) {
    // 按 type 分发到对应 Pinia store
    // transcript → transcriptStore.handleMessage(msg)
    // question_detected → questionsStore.handleQuestion(msg)
    // answer_chunk → questionsStore.handleAnswerChunk(msg)
    // active_qa_chunk → chatStore.handleChunk(msg)
    // 等等...
  }

  onUnmounted(() => {
    ws?.close()
    if (reconnectTimer) clearTimeout(reconnectTimer)
  })

  return { connected, connect, send }
}
```

### 5.2 Markdown 渲染管线

```typescript
// src/utils/markdown.ts
import { marked } from 'marked'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'

// 配置 marked 使用 highlight.js
marked.setOptions({
  highlight(code: string, lang: string) {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang }).value
    }
    return hljs.highlightAuto(code).value
  },
})

export function renderMarkdown(raw: string): string {
  const html = marked.parse(raw) as string
  return DOMPurify.sanitize(html)
}
```

### 5.3 浏览器标签页标题伪装

```typescript
// src/main.ts 或 App.vue 中
import { useSettingsStore } from './stores/settings'

// 设置伪装标题
const settings = useSettingsStore()
document.title = settings.tabTitle || '在线文档 - 编辑中'

// 用户也可在设置中自定义标题
```

### 5.4 精修文本淡入过渡

```css
/* src/styles/transitions.css */
.transcript-line {
  transition: opacity 0.3s ease-in-out;
}

.transcript-line.refining {
  opacity: 0.6;
}

.transcript-line.refined-enter {
  animation: fade-replace 0.3s ease-in-out;
}

@keyframes fade-replace {
  0%   { opacity: 0.4; }
  100% { opacity: 1; }
}
```

### 5.5 深色主题 CSS 变量

```css
/* src/styles/variables.css */
:root {
  /* 基础色板 */
  --bg-primary:     #111111;
  --bg-secondary:   #1a1a1a;
  --bg-tertiary:    #242424;
  --bg-elevated:    #2a2a2a;

  /* 文本色 */
  --text-primary:   #e0e0e0;
  --text-secondary: #999999;
  --text-muted:     #666666;      /* 中间结果 */

  /* 说话人颜色 */
  --speaker-teacher:  #5b9bd5;    /* 教师：蓝色 */
  --speaker-student:  #70ad47;    /* 学生：绿色 */
  --speaker-unknown:  #e0e0e0;    /* 未识别：白色 */

  /* 功能色 */
  --accent-primary:   #4a9eff;    /* 主要操作 */
  --accent-danger:    #ff4757;    /* 危险操作/录音中 */
  --accent-warning:   #ffa502;    /* 警告 */
  --accent-success:   #2ed573;    /* 成功/已精修 */

  /* 来源图标色 */
  --source-auto:    #5b9bd5;      /* 🔍 自动检测 */
  --source-manual:  #ffa502;      /* ✋ 手动触发 */
  --source-force:   #7c4dff;      /* 💬 强制生成 */
  --source-refined: #2ed573;      /* 🔄 精修补检 */

  /* 间距 */
  --spacing-xs: 4px;
  --spacing-sm: 8px;
  --spacing-md: 16px;
  --spacing-lg: 24px;
  --spacing-xl: 32px;

  /* 圆角 */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;

  /* 字号 */
  --font-size-xs:  12px;
  --font-size-sm:  13px;
  --font-size-md:  14px;
  --font-size-lg:  16px;
  --font-size-xl:  18px;

  /* 层级 */
  --z-dropdown:  100;
  --z-modal:     200;
  --z-toast:     300;
}
```

---

## 6. SQLAlchemy ORM 模型参考（后端对应）

以下为关键模型的 SQLAlchemy ORM 映射参考，与上述 DDL 完全对应：

```python
# app/models/base.py
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, Float, Boolean, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def gen_uuid() -> str:
    return str(uuid.uuid4())


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
```

```python
# app/models/session.py
from sqlalchemy import String, Integer, Float, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, gen_uuid, utcnow_iso


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"), default=None)
    course_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="created")
    started_at: Mapped[str | None] = mapped_column(String, default=None)
    stopped_at: Mapped[str | None] = mapped_column(String, default=None)

    refine_status: Mapped[str] = mapped_column(String, nullable=False, default="none")
    refine_progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refine_strategy: Mapped[str | None] = mapped_column(String, default=None)

    parent_session_id: Mapped[str | None] = mapped_column(String, default=None)
    total_duration: Mapped[float] = mapped_column(Float, default=0)
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utcnow_iso)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=utcnow_iso)

    # relationships
    recordings: Mapped[list["Recording"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    transcriptions: Mapped[list["Transcription"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    questions: Mapped[list["Question"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    chat_messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")
```

---

## 7. 附录：消息类型速查表

### Server → Client

| type | 场景 | 频率 |
|------|------|------|
| `transcript` | 实时转写片段 | 高频（每秒多次） |
| `transcript_translation` | 翻译结果 | 中频 |
| `refine_update` | 精修文本替换 | 低频 |
| `question_detected` | 检测到问题 | 低频（每节课若干次） |
| `answer_chunk` | 答案流式片段 | 中频（生成时每秒多次） |
| `answer_complete` | 答案生成完成 | 低频 |
| `answer_updated` | 精修后答案更新 | 低频 |
| `active_qa_chunk` | 主动提问回答片段 | 中频 |
| `active_qa_complete` | 主动提问回答完成 | 低频 |
| `refine_status` | 精修进度更新 | 低频 |
| `speaker_identified` | 说话人识别 | 低频 |
| `status` | 系统状态变更 | 低频 |
| `error` | 错误通知 | 极低频 |

### Client → Server

| type | 场景 |
|------|------|
| `command` | 控制指令（开始/停止/手动检测等） |
| `active_question` | 主动提问 |
| `heartbeat` | 心跳保活 |

---

*文档结束*
