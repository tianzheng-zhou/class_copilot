# class_copilot 代码审查报告

> 审查日期：2026-03-15  
> 审查范围：全部源代码  
> 严重程度分级：🔴 严重 / 🟠 高 / 🟡 中 / 🔵 低 / 💡 建议

---

## 目录

1. [代码健壮性](#1-代码健壮性)
2. [程序 Bug 与崩溃风险](#2-程序-bug-与崩溃风险)
3. [并发与线程安全问题](#3-并发与线程安全问题)
4. [性能问题](#4-性能问题)
5. [架构与设计问题](#5-架构与设计问题)
6. [功能优化建议](#6-功能优化建议)
7. [代码质量改进](#7-代码质量改进)

---

## 1. 代码健壮性

### 🔵 1.1 LLM 响应解析未充分验证

**文件**: `src/llm/question_detector.py`

**问题**: `detect()` 方法直接 `json.loads` LLM 返回结果，缺少对返回字段的类型验证。恶意或异常的 LLM 输出可能导致后续逻辑出错。

**改进方案**:
```python
def _parse_detection_result(self, response: str) -> dict | None:
    try:
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(text)
        # 类型验证
        if not isinstance(result.get("is_question"), bool):
            return None
        if not isinstance(result.get("confidence"), (int, float)):
            return None
        if not isinstance(result.get("question_text"), str):
            result["question_text"] = ""
        return result
    except (json.JSONDecodeError, IndexError, KeyError):
        return None
```

---

## 2. 程序 Bug 与崩溃风险

### 🔴 2.1 `SessionManager.cleanup()` 方法未实现

**文件**: `src/app.py` (第 74 行) → `src/core/session_manager.py`

**问题**: `App.run()` 的 `finally` 块调用 `self.session_mgr.cleanup()`，但 `SessionManager` 类中没有定义 `cleanup` 方法。程序退出时会抛出 `AttributeError`，导致资源无法正确释放（ASR 连接未断开、录音文件未关闭、数据库未关闭）。

**改进方案**: 在 `SessionManager` 中实现 `cleanup`:
```python
def cleanup(self) -> None:
    """清理所有资源。"""
    if self._is_listening:
        self.stop_session()
    self.db.close()
```

---

### 🔴 2.2 废弃的讯飞客户端代码应删除

**文件**: `src/asr/iflytek_client.py`, `src/asr/voiceprint.py`

**问题**: 讯飞 ASR 功能已全面替换为千问生态（DashScope），但 `iflytek_client.py` 和 `voiceprint.py` 仍留在代码库中。这两个文件存在大量问题：
- `iflytek_client.py` 导入了 `constants.py` 中不存在的常量（`ASR_LANG`, `ASR_PD`, `ASR_ROLE_TYPE`, `IFLYTEK_ASR_WS_URL`），import 即崩溃
- `voiceprint.py` 依赖未声明的 `aiohttp`，引用了不存在的讯飞声纹常量
- `voiceprint.py` 使用 `async def` 但项目没有 asyncio 事件循环

**改进方案**: 直接删除这两个废弃文件：
```
删除: src/asr/iflytek_client.py
删除: src/asr/voiceprint.py
```

同时清理 `constants.py` 中可能残留的讯飞相关常量（如有）。

---

### 🟠 2.3 `llm_filter_teacher_only` 默认值不一致

**文件**: `src/config/settings.py`

**问题**: `_DEFAULT_SETTINGS` 中 `"llm_filter_teacher_only"` 设为 `False`，但 `llm_filter_teacher_only` 属性的 `get` 默认值为 `True`。当配置文件存在但缺少该字段时（升级场景），行为与新安装不同。

```python
# _DEFAULT_SETTINGS 中
"llm_filter_teacher_only": False,

# 属性 getter 中
@property
def llm_filter_teacher_only(self) -> bool:
    return self._data.get("llm_filter_teacher_only", True)  # 默认值不一致！
```

**改进方案**: 统一默认值为 `False`（或统一为 `True`），并依赖 `_load()` 中的缺失字段填充逻辑。

---

### 🟠 2.4 `asr_model` 属性默认值不一致

**文件**: `src/config/settings.py`

**问题**: `_DEFAULT_SETTINGS` 中 `asr_model` 为 `"qwen3-asr-flash-realtime"`，但 `asr_model` 属性 getter 默认为 `"fun-asr-realtime"`。

```python
# _DEFAULT_SETTINGS
"asr_model": "qwen3-asr-flash-realtime",

# 属性
@property
def asr_model(self) -> str:
    return self._data.get("asr_model", "fun-asr-realtime")  # 不一致！
```

**改进方案**: 让属性 getter 的默认值与 `_DEFAULT_SETTINGS` 保持一致，或者更好的做法是不硬编码默认值：

```python
@property
def asr_model(self) -> str:
    return self._data.get("asr_model", _DEFAULT_SETTINGS["asr_model"])
```

---

### 🟡 2.5 ASR 重连竞态条件

**文件**: `src/core/session_manager.py`

**问题**: `_on_asr_disconnected` 使用 `threading.Timer(2.0, ...)` 延迟重连。如果在 2 秒内用户调用 `stop_session()`，定时器仍会触发 `_start_asr()`，可能导致已停止的会话重新建立 ASR 连接。

```python
def _on_asr_disconnected(self) -> None:
    if self._is_listening:
        threading.Timer(2.0, lambda: self._start_asr(self._session.course_name)).start()
```

**改进方案**:
```python
def _on_asr_disconnected(self) -> None:
    if self._is_listening:
        def _reconnect():
            # 重连前再次检查状态
            if self._is_listening and self._session:
                self._start_asr(self._session.course_name)
        threading.Timer(2.0, _reconnect).start()
```

---

### 🟡 2.6 `_session` 被后台线程访问时可能为 None

**文件**: `src/core/session_manager.py`

**问题**: `_handle_detected_question` 中创建后台线程 `_generate()`，该线程内部访问 `self._session.course_name` 和 `self._session.id`。如果在线程执行前用户停止了会话（`_session = None`），会抛出 `AttributeError`。

**改进方案**: 在启动线程前捕获必要的值：
```python
def _handle_detected_question(self, question_text: str, source: str) -> None:
    if not self._session or not self._answer_generator:
        return
    session_id = self._session.id
    course_name = self._session.course_name
    # ... 后续线程中使用 session_id 和 course_name 而不是 self._session
```

---

### 🟡 2.7 winotify 通知可能引发异常

**文件**: `src/utils/notifier.py`

**问题**: `notify_question_detected` 和 `notify_status` 没有异常处理。如果 Windows 通知服务不可用或 winotify 出错，会导致调用方（问题检测流程）中断。

**改进方案**:
```python
def notify_question_detected(question_text: str) -> None:
    try:
        toast = Notification(app_id=APP_NAME, title="检测到课堂提问", msg=question_text[:200])
        toast.set_audio(None, suppress=True)
        toast.show()
    except Exception:
        logger.debug("发送通知失败", exc_info=True)
```

---

## 3. 并发与线程安全问题

### 🔴 3.1 SQLite 多线程并发写入无锁保护

**文件**: `src/storage/database.py`

**问题**: SQLite 连接使用 `check_same_thread=False` 允许多线程访问，但没有使用锁来序列化写操作。以下后台线程都会并发写入数据库：
- ASR 回调线程 → `add_segment()`
- 问题检测线程 → `add_question()`
- 答案生成线程 → `update_question_answers()`
- 主动问答线程 → `add_active_qa()`

虽然 SQLite 的 WAL 模式支持并发读，但并发写仍可能导致 `sqlite3.OperationalError: database is locked`。

**改进方案**:
```python
import threading

class Database:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _execute_write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """线程安全的写操作。"""
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur
```

---

### 🟠 3.2 AudioCapture 资源释放存在竞态

**文件**: `src/asr/audio_capture.py`

**问题**: `stop()` 方法先设置 `self._running = False` 再 `join` 线程再关闭 stream。但 `_capture_loop` 内 `self._stream.read()` 可能正在阻塞，`join(timeout=2)` 超时后直接关闭 stream 可能导致 pyaudio 内部状态不一致。

**改进方案**: 先关闭 stream 使 `read()` 抛出异常退出循环，再 join 线程：
```python
def stop(self) -> None:
    self._running = False
    # 先停止 stream 使阻塞的 read() 返回
    if self._stream:
        try:
            self._stream.stop_stream()
        except Exception:
            pass
    if self._thread:
        self._thread.join(timeout=3)
        self._thread = None
    if self._stream:
        self._stream.close()
        self._stream = None
    if self._pa:
        self._pa.terminate()
        self._pa = None
```

---

### � 3.3 翻译阻塞 ASR 回调线程

**文件**: `src/core/session_manager.py`

**问题**: `_on_asr_result` 在 ASR 回调中同步调用 `self._translator.translate_to_chinese()`，这是一个网络请求（调用 LLM API），会阻塞 ASR 结果的接收和处理。

```python
# 英文翻译 — 同步调用，阻塞 ASR 线程
if (self.settings.language == "en" and self._translator
        and result.is_final and self.settings.get("translation_enabled", True)):
    segment.translation = self._translator.translate_to_chinese(result.text)
```

**改进方案**: 将翻译操作移到后台线程：
```python
if need_translation and result.is_final:
    def _translate(seg=segment):
        seg.translation = self._translator.translate_to_chinese(seg.text)
        # 更新数据库和 UI
        if seg.id:
            self.db.update_segment_translation(seg.id, seg.translation)
        if self.on_transcript_update:
            self.on_transcript_update(seg)
    threading.Thread(target=_translate, daemon=True).start()
```

---

## 4. 性能问题

### 🟠 4.1 答案生成串行调用两次 LLM

**文件**: `src/llm/answer_generator.py`

**问题**: `generate()` 方法顺序调用两次 `self._client.chat()`（简洁版 + 展开版），总耗时是两次 LLM 调用之和。对于 10 秒回答窗口的场景，这是不可接受的延迟。

**改进方案**: 并行调用两个 LLM 请求：
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def generate(self, question: str, context: str, course_name: str = "", language: str = "zh") -> tuple[str, str]:
    system = ANSWER_SYSTEM_PROMPT.format(course_name=course_name or "未知课程")
    if language == "en":
        system += "\n请同时用英文和中文回答。先英文，再给出中文翻译。"

    concise_msgs = [{"role": "system", "content": system},
                    {"role": "user", "content": CONCISE_PROMPT.format(context=context[-2000:], question=question)}]
    detailed_msgs = [{"role": "system", "content": system},
                     {"role": "user", "content": DETAILED_PROMPT.format(context=context[-2000:], question=question)}]

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_concise = pool.submit(self._client.chat, concise_msgs, LLM_MODEL_FLASH, 0.7)
        f_detailed = pool.submit(self._client.chat, detailed_msgs, LLM_MODEL_FLASH, 0.7)
        return f_concise.result(), f_detailed.result()
```

---

### 🟠 4.2 问题检测过于频繁，LLM 调用无节流

**文件**: `src/core/session_manager.py`

**问题**: 每一个 `is_final` 的 ASR 段落都会触发一次问题检测 LLM 调用。如果老师连续讲话，可能每隔几秒就产生一个 final segment，导致大量并发 LLM 请求。这既浪费 API 费用，也可能触发 API 限流。

**改进方案**:
1. **节流/防抖**: 收到 final segment 后等待 2-3 秒，如果期间收到新 segment，则合并后再检测
2. **批量检测**: 累积 3-5 个 segment 后一次性送检
3. **本地预过滤**: 先检查文本中是否包含疑问词（如"吗"、"呢"、"什么"、"为什么"、"谁"、"?"），只有匹配时才调用 LLM

```python
# 简单的本地预过滤
QUESTION_KEYWORDS = re.compile(r'[?？]|谁|什么|为什么|怎么|哪|吗|呢|想一想|回答|同学们')

def _auto_detect_question(self, segment: TranscriptSegment) -> None:
    if not QUESTION_KEYWORDS.search(segment.text):
        return  # 无疑问特征，跳过 LLM 调用
    # ... 继续原有逻辑
```

---

### 🟡 4.3 TranscriptManager 内存中段落列表无界增长

**文件**: `src/core/transcript.py`

**问题**: `_segments` 列表随课堂时间持续增长。90 分钟课堂可能产生数千个段落，全部驻留内存。`get_context_text()` 每次都要从尾部遍历。

**改进方案**:
- 使用 `collections.deque(maxlen=N)` 限制内存中保留的段落数
- `get_context_text` 的 `max_chars=3000` 限制意味着只需保留最近约 100 个段落

```python
from collections import deque

class TranscriptManager:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._segments: deque[TranscriptSegment] = deque(maxlen=500)
```

---

### 🟡 4.4 音频存储未定期刷盘

**文件**: `src/storage/audio_storage.py`

**问题**: MP3 编码数据只在 `write_chunk` 时写入文件，但文件的 `flush()` 只在 `stop_recording` 时通过 `close()` 隐式触发。如果应用崩溃，所有未 flush 的数据将丢失。

**改进方案**: 每 N 个 chunk 或每 M 秒调用一次 `self._file.flush()`：
```python
def write_chunk(self, pcm_data: bytes) -> None:
    if self._encoder and self._file:
        mp3_bytes = self._encoder.encode(pcm_data)
        if mp3_bytes:
            self._file.write(mp3_bytes)
            self._chunk_count += 1
            if self._chunk_count % 250 == 0:  # 约每 10 秒刷盘一次
                self._file.flush()
```

---

### 🔵 4.5 `list_devices()` 每次创建/销毁 PyAudio 实例

**文件**: `src/asr/audio_capture.py`

**问题**: `list_devices()` 是静态方法，每次调用都创建和销毁一个 `PyAudio` 实例，打开设置对话框时会有短暂卡顿。

**改进方案**: 缓存设备列表，或在后台线程中预加载。

---

## 5. 架构与设计问题

### 🟠 5.1 无数据库迁移策略

**文件**: `src/storage/database.py`

**问题**: 数据库 schema 使用 `CREATE TABLE IF NOT EXISTS` 直接创建。如果未来需要修改表结构（添加列、修改类型），已有的数据库不会被更新，导致新版本运行时出现列缺失错误。

**改进方案**: 引入版本化迁移机制：
```python
_MIGRATIONS = [
    # v1: 初始 schema
    _CREATE_TABLES_SQL,
    # v2: 添加索引
    "CREATE INDEX IF NOT EXISTS idx_segments_session ON transcript_segments(session_id);",
    # v3: 添加新列
    "ALTER TABLE sessions ADD COLUMN notes TEXT NOT NULL DEFAULT '';",
]

def initialize(self) -> None:
    cur_version = self.conn.execute("PRAGMA user_version").fetchone()[0]
    for i, migration in enumerate(_MIGRATIONS):
        if i >= cur_version:
            self.conn.executescript(migration)
    self.conn.execute(f"PRAGMA user_version = {len(_MIGRATIONS)}")
    self.conn.commit()
```

---

### 🟠 5.2 快捷键配置无法在设置界面中修改

**文件**: `src/ui/settings_dialog.py`

**问题**: 需求文档明确要求"快捷键可在设置中自定义修改"，但设置对话框中没有快捷键配置 Tab。

**改进方案**: 添加快捷键设置页面，参考 VS Code 的快捷键编辑器设计，使用 `QKeySequenceEdit` 组件让用户录入快捷键。

---

### 🟡 5.3 课程名历史不持久化

**文件**: `src/ui/main_window.py`

**问题**: 课程名 `QComboBox` 是可编辑的，但之前输入过的课程名在重启后丢失。用户每次都要重新输入。

**改进方案**: 从数据库中加载历史课程名并填充到 ComboBox：
```python
def _load_course_history(self) -> None:
    sessions = self._session_mgr.get_history_sessions()
    courses = list(dict.fromkeys(s.course_name for s in sessions if s.course_name))
    self._course_combo.addItems(courses)
```

---

### 🟡 5.4 无崩溃恢复机制

**问题**: 如果程序在录音过程中意外崩溃：
- 当前会话状态仍为 `RECORDING`，重启后不会自动提示恢复
- 音频文件未正确关闭（缺少 MP3 尾帧），但通常仍可播放
- 内存中的中间转写结果丢失

**改进方案**:
1. 启动时检查是否有状态为 `RECORDING` 的会话，提示用户是否续记
2. 使用 `atexit` 注册清理函数作为额外保障

```python
import atexit

class App:
    def __init__(self):
        # ...
        atexit.register(self._emergency_cleanup)

    def _emergency_cleanup(self):
        try:
            if self.session_mgr.is_listening:
                self.session_mgr.stop_session()
        except Exception:
            pass
```

---

### 🟡 5.5 LLM 上下文窗口硬编码

**文件**: `src/core/transcript.py`, `src/llm/answer_generator.py`

**问题**: `get_context_text(max_chars=3000)` 和 `context[-2000:]` 都是硬编码的字符限制。qwen3.5-flash 模型支持的上下文窗口远大于此，当前截断可能丢失重要的课堂上下文。

**改进方案**: 将上下文长度作为可配置参数，并根据模型能力动态调整：
```python
MODEL_CONTEXT_LIMITS = {
    "qwen3.5-flash": 30000,  # 字符数（约 8k token）
    "qwen3.5-plus": 60000,
}
```

---

### 🔵 5.6 缺少数据库索引

**文件**: `src/storage/database.py`

**问题**: `transcript_segments` 和 `detected_questions` 表频繁按 `session_id` 查询和排序，但没有创建索引。数据量增大后查询会变慢。

**改进方案**:
```sql
CREATE INDEX IF NOT EXISTS idx_segments_session ON transcript_segments(session_id, start_time_ms);
CREATE INDEX IF NOT EXISTS idx_questions_session ON detected_questions(session_id);
CREATE INDEX IF NOT EXISTS idx_active_qa_session ON active_qa(session_id);
```

---

## 6. 功能优化建议

### 💡 6.1 流式答案生成

**当前**: 答案生成等待 LLM 完整返回后才显示。  
**建议**: 利用已实现的 `chat_stream()` 方法，实现流式渲染答案。用户可以在答案生成过程中就开始阅读，大幅降低感知延迟。

---

### 💡 6.2 问题检测置信度可视化

**当前**: 仅 `confidence >= 0.7` 时触发。  
**建议**: 在 UI 上显示置信度指示器（如颜色条），高置信度自动通知，中等置信度静默显示供用户确认，低置信度忽略。

---

### 💡 6.3 答案质量增强 — 支持近几次课堂的上下文

**当前**: 答案生成仅基于当前课堂的转写内容。  
**建议**: 允许选择性引入同课程历史课堂的转写内容或笔记，提供更丰富的上下文。

---

### 💡 6.4 断网续传与离线缓冲

**当前**: 需求文档规定断网时继续录音但暂停转写，但代码中只有 ASR 断线重连逻辑，没有真正的离线录音缓存和恢复机制。  
**建议**: 
1. ASR 断开时，音频数据持续写入本地缓冲
2. 重连后，将离线期间的音频批量发送进行离线转写
3. UI 显示明确的在线/离线状态指示器

---

### 💡 6.5 答案一键复制优化

**当前**: 复制按钮复制纯文本。  
**建议**: 
- 自动去除 Markdown 格式标记
- 支持复制后自动隐藏窗口（隐蔽模式）
- 提供"复制并最小化"快捷操作

---

### 💡 6.6 重复问题去重

**当前**: 同一个问题可能被多次检测到（老师重复提问或 ASR 分段识别）。  
**建议**: 对新检测到的问题与最近 N 个问题做相似度比较（简单的字符串相似度即可），避免重复生成答案。

```python
from difflib import SequenceMatcher

def _is_duplicate_question(self, new_q: str, recent_questions: list[str], threshold=0.7) -> bool:
    for q in recent_questions:
        if SequenceMatcher(None, new_q, q).ratio() > threshold:
            return True
    return False
```

---

### 💡 6.7 ASR 连接状态指示

**建议**: 在状态栏显示 ASR 连接状态图标（绿色=已连接，黄色=重连中，红色=断开），让用户了解系统是否正在正常工作。

---

### 💡 6.8 支持拖拽角调整窗口大小的优化

**当前**: 窗口使用标准 Qt 窗口框架。  
**建议**: 考虑无边框窗口 + 自定义拖拽区域，更像真正的悬浮窗，且在课堂上更不显眼。

---


### 💡 6.10 课堂统计与分析

**建议**: 提供简单的统计功能：
- 本次课堂时长、检测到的问题数
- 老师发言占比 vs 学生发言占比
- 历史课堂记录统计图表

---

### 💡 6.11 导出格式扩展

**当前**: 仅支持 Markdown 导出。  
**建议**: 增加导出为 PDF、Word、纯文本等格式，方便课后复习。

---

### 💡 6.12 输入法兼容性

**问题**: 全局快捷键可能与输入法快捷键冲突（如 `Ctrl+Shift+S` 可能与搜狗输入法冲突）。  
**建议**: 
- 文档中提醒用户可能的冲突
- 支持检测快捷键冲突并提示用户
- 默认快捷键尽量避开常见输入法快捷键

---

## 7. 代码质量改进

### 🔵 7.1 `run.py` 中的依赖检测逻辑不可靠

**文件**: `run.py`

**问题**: `__import__(pkg.lower().replace("-", "_").split("[")[0])` 的包名转换逻辑不够健壮。例如 `PyQt6` 转换后尝试 import `pyqt6`，但实际模块名是 `PyQt6`（大小写敏感）。

**改进方案**: 使用 `importlib.util.find_spec` 进行更可靠的检测，或者维护一个包名到模块名的映射：
```python
PKG_MODULE_MAP = {
    "PyQt6": "PyQt6",
    "pyaudio": "pyaudio",
    "dashscope": "dashscope",
    "openai": "openai",
    "cryptography": "cryptography",
    "pynput": "pynput",
    "winotify": "winotify",
}

for pkg, module in PKG_MODULE_MAP.items():
    if importlib.util.find_spec(module) is None:
        missing.append(pkg)
```

---

### 🔵 7.2 缺少类型注解的回调参数

**文件**: 多个文件

**问题**: 很多回调属性类型为 `Callable[..., None] | None`，但实际签名不明确。例如 `on_error: Callable[[str], None] | None`，在一些地方调用时也没有做 None 检查（虽然目前都做了）。

**建议**: 考虑使用事件总线或信号机制（如 Qt Signal）替代回调属性，减少 None 检查样板代码。

---

### 🔵 7.3 无单元测试

**问题**: `pyproject.toml` 中声明了 `pytest` 依赖但没有任何测试文件。核心逻辑（问题检测解析、上下文文本拼接、音频编码）应该有测试覆盖。

**建议**: 优先为以下模块编写测试：
- `QuestionDetector._parse_result` → JSON 解析逻辑
- `TranscriptManager.get_context_text` → 上下文截断逻辑
- `KeyVault` → 加密/解密往返测试
- `AudioStorage` → MP3 编码写入测试
- `Database` → CRUD 操作

---

### 🔵 7.4 `_md_to_html` 简易转换器健壮性不足

**文件**: `src/ui/question_input.py`

**问题**: 自建的 Markdown → HTML 转换器对嵌套格式、复杂列表等支持不完整，且换行转换 (`\n` → `<br>`) 会在 `<pre>` 块内产生多余标签。

**建议**: 考虑引入轻量级 Markdown 库如 `markdown-it-py`（~100KB），或使用 QTextBrowser 的 Markdown 模式（Qt 5.14+）:
```python
self._history.setMarkdown(text)  # Qt 内置 Markdown 支持
```

---

### 🔵 7.5 缺少 `.gitignore`

**问题**: 未看到 `.gitignore` 文件，`__pycache__/`、`.venv/`、`*.log`、`*.db` 等应被忽略。

---

## 总结

| 类别 | 🔴 严重 | 🟠 高 | 🟡 中 | 🔵 低 | 💡 建议 |
|------|:-------:|:-----:|:-----:|:-----:|:-------:|
| 代码健壮性 | — | — | — | 1 | — |
| Bug/崩溃 | 2 | 2 | 3 | — | — |
| 并发/线程 | 1 | 1 | 1 | — | — |
| 性能问题 | — | 2 | 2 | 1 | — |
| 架构设计 | — | 2 | 3 | 1 | — |
| 功能优化 | — | — | — | — | 12 |
| 代码质量 | — | — | — | 5 | — |
| **合计** | **3** | **7** | **9** | **8** | **12** |

### 建议优先修复顺序

1. **P0 — 立即修复**: 2.1 (cleanup未实现), 2.2 (删除废弃讯飞代码), 3.1 (SQLite并发锁)
2. **P1 — 本周内**: 2.3/2.4 (默认值不一致), 2.5 (重连竞态), 3.3 (翻译阻塞), 4.1 (并行答案生成)
3. **P2 — 迭代改进**: 4.2 (问题检测节流), 5.1 (数据库迁移), 5.2 (快捷键设置), 5.4 (崩溃恢复)
4. **P3 — 持续优化**: 功能建议和代码质量改进
