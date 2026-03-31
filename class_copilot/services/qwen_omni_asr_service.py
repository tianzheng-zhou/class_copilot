"""实时 ASR 服务 - 基于 Qwen3.5-Omni-Realtime 全模态模型

利用 qwen3.5-omni 系列 Realtime 模型进行实时语音转写：
  - 连接: wss://dashscope.aliyuncs.com/api-ws/v1/realtime
  - 模型: qwen3.5-omni-flash-realtime / qwen3.5-omni-plus-realtime
  - 音频: PCM 16-bit, 通过 base64 发送
  - 结果: 模型文本回复通道 (response.text.delta / response.text.done)

相比 qwen3-asr-flash-realtime:
  - 更强的语言理解能力 (与 Qwen3.5-Plus 同级)
  - 支持 113 种语种和方言的语音识别
  - 通过 instructions (system prompt) 可自定义转写行为
  - 内置 VAD，自动检测语音起止
"""

import asyncio
import base64
import json
import time
import uuid

from dashscope.audio.qwen_omni import OmniRealtimeConversation, OmniRealtimeCallback

from loguru import logger
from class_copilot.config import settings
from class_copilot.logger import asr_logger


# 轮换时保留的最近转写条数上限
_RECENT_FINALS_LIMIT = 30


def _build_asr_instructions(language: str = "zh", hot_words: str = "",
                            prior_context: str = "") -> str:
    """构建 Qwen3.5-Omni-Realtime 的 ASR 转写系统提示词 (XML 结构)

    Args:
        prior_context: 会话轮换时注入的前文转写内容，使模型保持上下文连贯。
    """

    lang_desc = {
        "zh": "中文（普通话）",
        "en": "English",
    }.get(language, language)

    hot_words_section = ""
    if hot_words and hot_words.strip():
        words = [w.strip() for w in hot_words.replace("\uff0c", ",").split(",") if w.strip()]
        if words:
            words_list = "\n".join(f"    <word>{w}</word>" for w in words)
            hot_words_section = f"""
<hot_words>
  <description>以下是本次课堂中可能出现的专业术语和高频词汇，请在转写时优先识别这些词汇并确保拼写正确。</description>
  <words>
{words_list}
  </words>
</hot_words>"""

    instructions = """<role>
  <identity>你是一个专业的课堂实时语音转写助手。</identity>
  <task>你的唯一任务是将麦克风输入的音频流精准地转录为文字，不做任何其他回应。</task>
</role>

<transcription_rules>
  <language>{lang_desc}</language>
  <critical_rules>
    <rule>你必须完整转录听到的每一句话，不得省略、跳过或概括任何内容。</rule>
    <rule>严格按照说话人的原话进行逐字转录，保持原始表述。即使听起来不完整或像在自言自语，也必须如实输出。</rule>
    <rule>禁止输出你没有从音频中听到的内容。不要猜测、补充或编造。</rule>
  </critical_rules>
  <formatting_rules>
    <rule>正确使用标点符号，句子结束时添加句号、问号或感叹号。</rule>
    <rule>对于专业术语、人名、地名等，优先使用通用的正确拼写。</rule>
    <rule>保留口语化表达和语气词（如 "嗯"、"那个"、"uh"、"so" 等），保持转录的真实性。</rule>
    <rule>数字、公式、单位等按照学术规范转写。</rule>
  </formatting_rules>
</transcription_rules>

<context>
  <scenario>大学课堂实时授课</scenario>
  <audio_environment>课堂环境，可能包含背景噪音、学生讨论声。</audio_environment>
  <primary_speaker>授课教师</primary_speaker>
</context>{hot_words_section}

<output_format>
  <rules>
    <rule>仅输出转录文本，不添加任何解释、翻译、总结或额外内容。</rule>
    <rule>每次输出应包含你从当前音频片段中听到的所有内容，不要遗漏。</rule>
  </rules>
</output_format>{prior_section}"""

    # 会话轮换时注入前文转写，帮助模型衔接上下文
    prior_section = ""
    if prior_context and prior_context.strip():
        prior_section = f"""

<prior_transcript>
  <description>以下是本次课堂此前的转写内容（因技术原因进行了连接刷新）。请基于这些上下文继续转写，保持内容连贯。不要重复输出以下内容。</description>
  <text>{prior_context}</text>
</prior_transcript>"""

    return instructions.format(
        lang_desc=lang_desc,
        hot_words_section=hot_words_section,
        prior_section=prior_section,
    )


class _QwenOmniASRCallback(OmniRealtimeCallback):
    """qwen3.5-omni-*-realtime 回调处理器

    仅使用 response.text.delta / response.text.done 通道（模型文本回复）。
    不启用 input_audio_transcription 旁路转写，避免同一段音频产生两份文本导致重复。
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, result_queue: asyncio.Queue, on_disconnect=None):
        self._loop = loop
        self._result_queue = result_queue
        self._on_disconnect = on_disconnect
        # 累积当前 response 的增量文本
        self._response_text_buf: str = ""
        # session.updated 就绪信号
        self._session_ready = asyncio.Event()
        # 计时：记录首条文本输出的延迟
        self._start_ts: float = 0
        self._first_text_logged = False
        # 最近的 final 转写文本，用于会话轮换时注入上下文
        self._recent_finals: list[str] = []

    def _notify_disconnect(self, error_code=None):
        if self._on_disconnect:
            self._on_disconnect(error_code=error_code)

    def _emit(self, text: str, is_final: bool):
        """向队列推送一条转写结果"""
        if not text.strip():
            return
        if not self._first_text_logged and self._start_ts:
            elapsed = time.monotonic() - self._start_ts
            asr_logger.info("Omni ASR 首条文本输出延迟: {:.2f}s", elapsed)
            self._first_text_logged = True
        msg = {
            "text": text,
            "is_final": is_final,
            "start_time": 0,
            "end_time": 0,
            "speaker_label": "UNKNOWN",
            "sentence_id": 0,
        }
        asr_logger.debug("Omni ASR [final={}]: {}", is_final, text)
        self._loop.call_soon_threadsafe(self._result_queue.put_nowait, msg)

    def on_open(self) -> None:
        asr_logger.info("ASR 连接已建立 (qwen3.5-omni-realtime)")

    def on_close(self, close_status_code, close_msg) -> None:
        asr_logger.info("ASR 连接已关闭: code={}, msg={}", close_status_code, close_msg)
        # 如果还有未 flush 的文本，作为 final 推送
        if self._response_text_buf.strip():
            self._emit(self._response_text_buf, True)
            self._response_text_buf = ""
        self._notify_disconnect(error_code=close_status_code if close_status_code != 1000 else None)

    def on_event(self, event) -> None:
        """处理服务端事件（SDK 传入已解析的 dict）"""
        try:
            event_type = event.get("type", "") if isinstance(event, dict) else ""

            # ── 模型文本回复（唯一转写通道）──
            if event_type == "response.text.delta":
                delta = event.get("delta", "")
                if delta:
                    self._response_text_buf += delta
                    # 推送 interim 结果使前端实时显示
                    self._emit(self._response_text_buf, False)

            elif event_type == "response.audio_transcript.delta":
                # 当 output_modalities 包含 audio 时，文本在此通道
                delta = event.get("delta", "")
                if delta:
                    self._response_text_buf += delta
                    self._emit(self._response_text_buf, False)

            elif event_type == "response.text.done":
                # 文本回复完成 → 取服务端的完整文本作为 final
                full_text = event.get("text", "") or self._response_text_buf
                if full_text.strip():
                    self._emit(full_text, True)
                    self._remember_final(full_text)
                self._response_text_buf = ""

            elif event_type == "response.audio_transcript.done":
                full_text = event.get("transcript", "") or self._response_text_buf
                if full_text.strip():
                    self._emit(full_text, True)
                    self._remember_final(full_text)
                self._response_text_buf = ""

            elif event_type == "response.done":
                # 整个响应结束，如果还有残余文本（兜底）
                if self._response_text_buf.strip():
                    self._emit(self._response_text_buf, True)
                self._response_text_buf = ""

            elif event_type == "response.created":
                # 新一轮回复开始，清空缓冲
                self._response_text_buf = ""

            # ── VAD ──
            elif event_type == "input_audio_buffer.speech_started":
                asr_logger.debug("VAD: 检测到语音开始")
            elif event_type == "input_audio_buffer.speech_stopped":
                asr_logger.debug("VAD: 检测到语音结束")

            # ── 错误 ──
            elif event_type == "error":
                err_msg = event.get("error", {}).get("message", "unknown")
                err_code = event.get("error", {}).get("code", "")
                asr_logger.error("Omni ASR 错误事件: code={}, msg={}", err_code, err_msg)
                if err_code in ("invalid_api_key", "authentication_error"):
                    self._notify_disconnect(error_code=401)

            # ── session 事件 ──
            elif event_type == "session.created":
                asr_logger.info("Omni ASR 会话已创建")
            elif event_type == "session.updated":
                asr_logger.info("Omni ASR 会话配置已确认 (session.updated)")
                self._loop.call_soon_threadsafe(self._session_ready.set)

            # ── 调试：记录未处理的事件类型 ──
            elif event_type:
                asr_logger.debug("Omni ASR 未处理事件: {}", event_type)

        except Exception as e:
            asr_logger.error("处理 Omni ASR 事件异常: {}", e)

    def _remember_final(self, text: str):
        """记住最近的 final 转写文本（环形缓冲）"""
        self._recent_finals.append(text.strip())
        if len(self._recent_finals) > _RECENT_FINALS_LIMIT:
            self._recent_finals = self._recent_finals[-_RECENT_FINALS_LIMIT:]

    def get_recent_context(self) -> str:
        """返回最近转写的拼接文本，用于会话轮换时注入提示词"""
        return "".join(self._recent_finals)


class QwenOmniRealtimeASRService:
    """实时 ASR 管理（qwen3.5-omni OmniRealtime WebSocket）

    Qwen-Omni-Realtime 存在两项硬限制：
      1. 单次 WebSocket 会话最长 120 分钟
      2. 上下文上限 262,144 tokens（输入 max ~196,608）
    音频以 ~25 token/s 速率消耗上下文，约 131 分钟就会撞上限。
    因此需要定期轮换会话（rotate），在 context 膨胀前主动重连。
    """

    # 轮换间隔从 config 读取，动态属性以支持运行时调整
    @property
    def _rotate_interval(self) -> float:
        return settings.asr_session_rotate_minutes * 60

    def __init__(self):
        self._conversation: OmniRealtimeConversation | None = None
        self._callback: _QwenOmniASRCallback | None = None
        self.result_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._disconnected = False
        self._last_error_code: int | None = None
        # 缓存 start() 参数，用于轮换时重建
        self._hot_words: str = ""
        self._language: str = "zh"
        # 会话启动时间，用于判断是否需要轮换
        self._session_started_at: float = 0
        # 轮换锁，防止并发轮换
        self._rotating = False

    async def pre_connect(self):
        """预连接 WebSocket（可在准备热词等操作的同时并行调用以减少启动延迟）"""
        if self._running or self._conversation:
            return
        t0 = time.monotonic()
        loop = asyncio.get_event_loop()
        self._callback = _QwenOmniASRCallback(loop, self.result_queue, on_disconnect=self._on_asr_disconnect)

        model = settings.asr_model
        self._conversation = OmniRealtimeConversation(
            model=model,
            callback=self._callback,
            api_key=settings.dashscope_api_key,
        )
        await asyncio.to_thread(self._conversation.connect)
        t1 = time.monotonic()
        asr_logger.info("Omni ASR connect() 耗时: {:.2f}s", t1 - t0)

    async def start(self, hot_words: str = "", language: str = "zh",
                    prior_context: str = ""):
        """启动实时 ASR（若未调用 pre_connect 则内部自动连接）

        Args:
            prior_context: 会话轮换时传入的前文转写，会注入到 instructions 中。
        """
        if self._running:
            asr_logger.warning("Omni ASR 已在运行中")
            return

        # 若未预连接，在此处连接
        if not self._conversation:
            await self.pre_connect()
        t1 = time.monotonic()

        # 构建转写引导提示词
        instructions = _build_asr_instructions(
            language=language, hot_words=hot_words, prior_context=prior_context)

        # 手动构建 session.update 消息，绕过 SDK 的 update_session()
        # SDK 总会将 voice 字段发送为 null 或具体值，而 omni-realtime 模型
        # 在仅输出文本时也会校验 voice 有效性。手动构建跳过 voice 字段。
        session_config = {
            "modalities": ["text"],
            "input_audio_format": "pcm",
            "instructions": instructions,
            # 显式关闭旁路转写通道，避免额外消耗 context tokens
            "input_audio_transcription": None,
            "turn_detection": {
                "type": "server_vad",
                "threshold": settings.vad_threshold,
                "prefix_padding_ms": settings.vad_prefix_padding_ms,
                "silence_duration_ms": settings.vad_silence_duration_ms,
            },
        }
        session_update_msg = json.dumps({
            "event_id": "event_" + uuid.uuid4().hex,
            "type": "session.update",
            "session": session_config,
        })
        await asyncio.to_thread(self._conversation.send_raw, session_update_msg)

        # 等待 session.updated 确认，避免在配置生效前发送音频（音频会被丢弃）
        try:
            await asyncio.wait_for(self._callback._session_ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            asr_logger.warning("等待 session.updated 超时 (10s)，继续运行")
        t2 = time.monotonic()
        asr_logger.info("Omni ASR session.update 确认耗时: {:.2f}s", t2 - t1)

        self._callback._start_ts = time.monotonic()
        self._running = True
        self._disconnected = False
        self._last_error_code = None
        self._hot_words = hot_words
        self._language = language
        self._session_started_at = time.monotonic()
        asr_logger.info("Omni 实时 ASR 已启动, 模型={}, 语言={}", settings.asr_model, language)

    async def send_audio(self, audio_bytes: bytes):
        """发送 PCM 音频帧（base64 编码后发送）"""
        if self._conversation and self._running and not self._disconnected:
            try:
                audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
                await asyncio.to_thread(self._conversation.append_audio, audio_b64)
            except Exception as e:
                if not self._disconnected:
                    self._disconnected = True
                    asr_logger.error("Omni ASR 连接已断开，停止发送音频: {}", e)

    async def stop(self):
        """停止 ASR — 直接关闭 WebSocket 连接，无需 end_session()"""
        if self._conversation and self._running:
            try:
                # 官方示例直接 close()，无需 end_session()（后者会等待 session.finished 导致延迟）
                await asyncio.to_thread(self._conversation.close)
            except Exception as e:
                if not self._disconnected:
                    asr_logger.error("关闭 Omni ASR 异常: {}", e)
            finally:
                self._running = False
                self._disconnected = False
                self._conversation = None
                asr_logger.info("Omni 实时 ASR 已停止")

    def _on_asr_disconnect(self, error_code=None):
        """ASR 服务端断开回调"""
        if not self._disconnected:
            self._disconnected = True
            if error_code is not None:
                self._last_error_code = error_code
            asr_logger.warning("Omni ASR 服务端连接断开 (error_code={})", error_code)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_disconnected(self) -> bool:
        return self._disconnected

    @property
    def is_permanent_error(self) -> bool:
        """是否为不可恢复的错误（如认证失败）"""
        return self._last_error_code in (401, 403)

    @property
    def needs_rotation(self) -> bool:
        """当前会话是否需要轮换（接近 context / 时间上限）"""
        if not self._running or not self._session_started_at:
            return False
        elapsed = time.monotonic() - self._session_started_at
        return elapsed >= self._rotate_interval

    async def rotate_session(self):
        """轮换 WebSocket 会话：关闭旧连接 → 新建连接 → 重新配置

        在 VAD 静音间隙调用，丢失极少量音频（<1s），前端基本无感。
        旧 callback 中的最近转写内容会被注入新会话的 instructions，保持上下文连续。
        """
        if self._rotating or not self._running:
            return
        self._rotating = True
        try:
            elapsed = time.monotonic() - self._session_started_at
            asr_logger.info("Omni ASR 会话轮换开始 (已运行 {:.0f}s)", elapsed)

            # 1) 从旧 callback 提取最近转写文本
            prior_context = ""
            if self._callback:
                prior_context = self._callback.get_recent_context()
                asr_logger.info("轮换携带前文上下文: {}字", len(prior_context))

            # 2) 关闭旧连接
            old_conv = self._conversation
            self._conversation = None
            self._running = False
            if old_conv:
                try:
                    await asyncio.to_thread(old_conv.close)
                except Exception:
                    pass

            # 3) 重新连接 + 配置（注入前文上下文）
            self._disconnected = False
            self._last_error_code = None
            await self.pre_connect()
            await self.start(
                hot_words=self._hot_words,
                language=self._language,
                prior_context=prior_context,
            )

            asr_logger.info("Omni ASR 会话轮换完成")
        except Exception as e:
            asr_logger.error("Omni ASR 会话轮换失败: {}", e)
            self._disconnected = True
        finally:
            self._rotating = False
