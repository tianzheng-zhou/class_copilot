"""实时 ASR 服务 - DashScope 千问 qwen3-asr 流式语音识别

基于 OmniRealtime WebSocket 协议:
  - 连接: wss://dashscope.aliyuncs.com/api-ws/v1/realtime
  - 模型: qwen3-asr-flash-realtime
  - 音频: PCM 16-bit, 通过 base64 发送
  - 结果: JSON 事件 (conversation.item.input_audio_transcription.text / .completed)
"""

import asyncio
import base64

from dashscope.audio.qwen_omni import OmniRealtimeConversation, OmniRealtimeCallback
from dashscope.audio.qwen_omni.omni_realtime import MultiModality, TranscriptionParams

from loguru import logger
from class_copilot.config import settings
from class_copilot.logger import asr_logger


class _QwenASRCallback(OmniRealtimeCallback):
    """qwen3-asr-flash-realtime 回调处理器"""

    def __init__(self, loop: asyncio.AbstractEventLoop, result_queue: asyncio.Queue, on_disconnect=None):
        self._loop = loop
        self._result_queue = result_queue
        self._on_disconnect = on_disconnect
        self._current_text = ""

    def _notify_disconnect(self, error_code=None):
        if self._on_disconnect:
            self._on_disconnect(error_code=error_code)

    def on_open(self) -> None:
        asr_logger.info("ASR 连接已建立 (qwen3-asr)")

    def on_close(self, close_status_code, close_msg) -> None:
        asr_logger.info("ASR 连接已关闭: code={}, msg={}", close_status_code, close_msg)
        self._notify_disconnect(error_code=close_status_code if close_status_code != 1000 else None)

    def on_event(self, event) -> None:
        """处理服务端事件（SDK 传入已解析的 dict）"""
        try:
            event_type = event.get("type", "") if isinstance(event, dict) else ""

            if event_type == "conversation.item.input_audio_transcription.text":
                # 中间结果（非 final），字段名为 stash
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
                    asr_logger.debug("ASR结果 [final=False]: {}", text)
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
                    asr_logger.debug("ASR结果 [final=True]: {}", text)
                    self._loop.call_soon_threadsafe(self._result_queue.put_nowait, msg)

            elif event_type == "error":
                err_msg = event.get("error", {}).get("message", "unknown")
                err_code = event.get("error", {}).get("code", "")
                asr_logger.error("ASR 错误事件: code={}, msg={}", err_code, err_msg)
                if err_code in ("invalid_api_key", "authentication_error"):
                    self._notify_disconnect(error_code=401)

            elif event_type == "input_audio_buffer.speech_started":
                asr_logger.debug("VAD: 检测到语音开始")
            elif event_type == "input_audio_buffer.speech_stopped":
                asr_logger.debug("VAD: 检测到语音结束")

        except Exception as e:
            asr_logger.error("处理ASR事件异常: {}", e)


class RealtimeASRService:
    """实时 ASR 管理（qwen3-asr OmniRealtime WebSocket）"""

    def __init__(self):
        self._conversation: OmniRealtimeConversation | None = None
        self._callback: _QwenASRCallback | None = None
        self.result_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._disconnected = False
        self._last_error_code: int | None = None

    async def start(self, hot_words: str = "", language: str = "zh"):
        """启动实时 ASR"""
        if self._running:
            asr_logger.warning("ASR 已在运行中")
            return

        loop = asyncio.get_event_loop()
        self._callback = _QwenASRCallback(loop, self.result_queue, on_disconnect=self._on_asr_disconnect)

        # 语言映射（qwen3-asr 支持 BCP-47 风格的简写）
        lang_map = {"zh": "zh", "en": "en"}

        self._conversation = OmniRealtimeConversation(
            model=settings.asr_model,
            callback=self._callback,
            api_key=settings.dashscope_api_key,
        )

        # 在线程中建连（WebSocket 是同步阻塞的）
        await asyncio.to_thread(self._conversation.connect)

        # 配置 session: 只输出文本，开启 VAD 和转写
        transcription_params = TranscriptionParams(
            language=lang_map.get(language, "zh"),
            sample_rate=settings.sample_rate,
            input_audio_format="pcm",
        )
        # 热词通过 corpus_text 传递（官方推荐方式）
        if hot_words:
            transcription_params.corpus_text = hot_words

        await asyncio.to_thread(
            self._conversation.update_session,
            output_modalities=[MultiModality.TEXT],
            transcription_params=transcription_params,
            enable_turn_detection=True,
            turn_detection_type="server_vad",
        )

        self._running = True
        self._disconnected = False
        self._last_error_code = None
        asr_logger.info("实时 ASR 已启动, 模型={}, 语言={}", settings.asr_model, language)

    async def send_audio(self, audio_bytes: bytes):
        """发送 PCM 音频帧（base64 编码后发送）"""
        if self._conversation and self._running and not self._disconnected:
            try:
                audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
                self._conversation.append_audio(audio_b64)
            except Exception as e:
                if not self._disconnected:
                    self._disconnected = True
                    asr_logger.error("ASR 连接已断开，停止发送音频: {}", e)

    async def stop(self):
        """停止 ASR"""
        if self._conversation and self._running:
            try:
                await asyncio.to_thread(self._conversation.end_session)
            except Exception as e:
                if not self._disconnected:
                    asr_logger.error("停止ASR异常: {}", e)
            finally:
                try:
                    self._conversation.close()
                except Exception:
                    pass
                self._running = False
                self._disconnected = False
                self._conversation = None
                asr_logger.info("实时 ASR 已停止")

    def _on_asr_disconnect(self, error_code=None):
        """ASR 服务端断开回调"""
        if not self._disconnected:
            self._disconnected = True
            if error_code is not None:
                self._last_error_code = error_code
            asr_logger.warning("ASR 服务端连接断开 (error_code={})", error_code)

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
