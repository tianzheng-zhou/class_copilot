"""实时 ASR 服务 - 基于 Qwen3.5-Omni-Realtime 全模态模型

利用 qwen3.5-omni 系列 Realtime 模型进行实时语音转写：
  - 连接: wss://dashscope.aliyuncs.com/api-ws/v1/realtime
  - 模型: qwen3.5-omni-flash-realtime / qwen3.5-omni-plus-realtime
  - 音频: PCM 16-bit, 通过 base64 发送
  - 结果: JSON 事件 (conversation.item.input_audio_transcription.text / .completed)

相比 qwen3-asr-flash-realtime:
  - 更强的语言理解能力 (与 Qwen3.5-Plus 同级)
  - 支持 113 种语种和方言的语音识别
  - 通过 instructions (system prompt) 可自定义转写行为
  - 内置 VAD，自动检测语音起止
"""

import asyncio
import base64

from dashscope.audio.qwen_omni import OmniRealtimeConversation, OmniRealtimeCallback
from dashscope.audio.qwen_omni.omni_realtime import MultiModality

from loguru import logger
from class_copilot.config import settings
from class_copilot.logger import asr_logger


def _build_asr_instructions(language: str = "zh", hot_words: str = "") -> str:
    """构建 Qwen3.5-Omni-Realtime 的 ASR 转写系统提示词 (XML 结构)"""

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

    return f"""<role>
  <identity>你是一个专业的课堂实时语音转写助手。</identity>
  <task>你的唯一任务是将麦克风输入的音频流精准地转录为文字，不做任何其他回应。</task>
</role>

<transcription_rules>
  <language>{lang_desc}</language>
  <guidelines>
    <rule>严格按照说话人的原话进行逐字转录，保持原始表述。</rule>
    <rule>正确使用标点符号，句子结束时添加句号、问号或感叹号。</rule>
    <rule>对于专业术语、人名、地名等，优先使用通用的正确拼写。</rule>
    <rule>保留口语化表达和语气词（如"嗯"、"那个"等），保持转录的真实性。</rule>
    <rule>数字、公式、单位等按照学术规范转写。</rule>
  </guidelines>
</transcription_rules>

<context>
  <scenario>大学课堂实时授课</scenario>
  <audio_environment>课堂环境，可能包含背景噪音、学生讨论声。</audio_environment>
  <primary_speaker>授课教师</primary_speaker>
</context>{hot_words_section}

<output_format>
  <instruction>仅输出转录文本，不添加任何解释、翻译、总结或额外内容。</instruction>
</output_format>"""


class _QwenOmniASRCallback(OmniRealtimeCallback):
    """qwen3.5-omni-*-realtime 回调处理器"""

    def __init__(self, loop: asyncio.AbstractEventLoop, result_queue: asyncio.Queue, on_disconnect=None):
        self._loop = loop
        self._result_queue = result_queue
        self._on_disconnect = on_disconnect

    def _notify_disconnect(self, error_code=None):
        if self._on_disconnect:
            self._on_disconnect(error_code=error_code)

    def on_open(self) -> None:
        asr_logger.info("ASR 连接已建立 (qwen3.5-omni-realtime)")

    def on_close(self, close_status_code, close_msg) -> None:
        asr_logger.info("ASR 连接已关闭: code={}, msg={}", close_status_code, close_msg)
        self._notify_disconnect(error_code=close_status_code if close_status_code != 1000 else None)

    def on_event(self, event) -> None:
        """处理服务端事件（SDK 传入已解析的 dict）"""
        try:
            event_type = event.get("type", "") if isinstance(event, dict) else ""

            if event_type == "conversation.item.input_audio_transcription.text":
                # 中间结果（非 final）
                text = event.get("stash", "")
                if text.strip():
                    msg = {
                        "text": text,
                        "is_final": False,
                        "start_time": 0,
                        "end_time": 0,
                        "speaker_label": "UNKNOWN",
                        "sentence_id": 0,
                    }
                    asr_logger.debug("Omni ASR [final=False]: {}", text)
                    self._loop.call_soon_threadsafe(self._result_queue.put_nowait, msg)

            elif event_type == "conversation.item.input_audio_transcription.completed":
                # 最终确认结果
                text = event.get("transcript", "")
                if text.strip():
                    msg = {
                        "text": text,
                        "is_final": True,
                        "start_time": 0,
                        "end_time": 0,
                        "speaker_label": "UNKNOWN",
                        "sentence_id": 0,
                    }
                    asr_logger.debug("Omni ASR [final=True]: {}", text)
                    self._loop.call_soon_threadsafe(self._result_queue.put_nowait, msg)

            elif event_type == "error":
                err_msg = event.get("error", {}).get("message", "unknown")
                err_code = event.get("error", {}).get("code", "")
                asr_logger.error("Omni ASR 错误事件: code={}, msg={}", err_code, err_msg)
                if err_code in ("invalid_api_key", "authentication_error"):
                    self._notify_disconnect(error_code=401)

            elif event_type == "input_audio_buffer.speech_started":
                asr_logger.debug("VAD: 检测到语音开始")
            elif event_type == "input_audio_buffer.speech_stopped":
                asr_logger.debug("VAD: 检测到语音结束")

        except Exception as e:
            asr_logger.error("处理 Omni ASR 事件异常: {}", e)


class QwenOmniRealtimeASRService:
    """实时 ASR 管理（qwen3.5-omni OmniRealtime WebSocket）"""

    def __init__(self):
        self._conversation: OmniRealtimeConversation | None = None
        self._callback: _QwenOmniASRCallback | None = None
        self.result_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._disconnected = False
        self._last_error_code: int | None = None

    async def start(self, hot_words: str = "", language: str = "zh"):
        """启动实时 ASR"""
        if self._running:
            asr_logger.warning("Omni ASR 已在运行中")
            return

        loop = asyncio.get_event_loop()
        self._callback = _QwenOmniASRCallback(loop, self.result_queue, on_disconnect=self._on_asr_disconnect)

        model = settings.asr_model

        self._conversation = OmniRealtimeConversation(
            model=model,
            callback=self._callback,
            api_key=settings.dashscope_api_key,
        )

        # 在线程中建连（WebSocket 是同步阻塞的）
        await asyncio.to_thread(self._conversation.connect)

        # 构建转写引导提示词
        instructions = _build_asr_instructions(language=language, hot_words=hot_words)

        # 配置 session: 仅输出文本，开启 VAD，通过 instructions 引导转写行为
        await asyncio.to_thread(
            self._conversation.update_session,
            output_modalities=[MultiModality.TEXT],
            instructions=instructions,
            input_audio_format="pcm",
            enable_turn_detection=True,
            turn_detection_type="server_vad",
        )

        self._running = True
        self._disconnected = False
        self._last_error_code = None
        asr_logger.info("Omni 实时 ASR 已启动, 模型={}, 语言={}", model, language)

    async def send_audio(self, audio_bytes: bytes):
        """发送 PCM 音频帧（base64 编码后发送）"""
        if self._conversation and self._running and not self._disconnected:
            try:
                audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
                self._conversation.append_audio(audio_b64)
            except Exception as e:
                if not self._disconnected:
                    self._disconnected = True
                    asr_logger.error("Omni ASR 连接已断开，停止发送音频: {}", e)

    async def stop(self):
        """停止 ASR"""
        if self._conversation and self._running:
            try:
                await asyncio.to_thread(self._conversation.end_session)
            except Exception as e:
                if not self._disconnected:
                    asr_logger.error("停止 Omni ASR 异常: {}", e)
            finally:
                try:
                    self._conversation.close()
                except Exception:
                    pass
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
