"""阿里云百炼 DashScope 实时语音识别客户端。

支持两种 ASR 模型：
- fun-asr-realtime: 使用 Recognition SDK，课堂/演讲场景优化
- qwen3-asr-flash-realtime: 使用 OmniRealtime WebSocket API，多语种高精度
"""

from __future__ import annotations

import base64
import enum
import logging
import threading
import time
from typing import Callable, Protocol

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

from src.config.constants import AUDIO_SAMPLE_RATE

# 单次 WebSocket 会话最长 120 分钟，在这之前主动刷新
_QWEN_SESSION_MAX_SEC = 110 * 60  # 110 分钟时主动重连


class ASRState(enum.Enum):
    """ASR 连接状态。"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"

logger = logging.getLogger(__name__)


class TranscriptResult:
    """转写结果。"""

    def __init__(self, text: str, is_final: bool,
                 start_ms: int = 0, end_ms: int = 0) -> None:
        self.text = text
        self.is_final = is_final
        self.start_ms = start_ms
        self.end_ms = end_ms


class ASRClient(Protocol):
    """ASR 客户端协议。"""

    def connect(self) -> None: ...
    def feed_audio(self, pcm_data: bytes) -> None: ...
    def disconnect(self) -> None: ...

    @property
    def is_connected(self) -> bool: ...


# ─────────────────────────────────────────────
# Fun-ASR 客户端（Recognition SDK）
# ─────────────────────────────────────────────

class _ASRCallback(RecognitionCallback):
    """DashScope ASR 回调处理。"""

    def __init__(
        self,
        on_result: Callable[[TranscriptResult], None] | None,
        on_error: Callable[[str], None] | None,
        on_connected: Callable[[], None] | None,
        on_disconnected: Callable[[], None] | None,
    ) -> None:
        self._on_result = on_result
        self._on_error = on_error
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._last_sentence_texts: dict[int, str] = {}

    def on_open(self) -> None:
        logger.info("Fun-ASR 已连接")
        if self._on_connected:
            self._on_connected()

    def on_close(self) -> None:
        logger.info("Fun-ASR 已断开")
        if self._on_disconnected:
            self._on_disconnected()

    def on_error(self, result: RecognitionResult) -> None:
        msg = str(result)
        logger.error("Fun-ASR 错误: %s", msg)
        if self._on_error:
            self._on_error(msg)

    def on_event(self, result: RecognitionResult) -> None:
        """处理转写事件。"""
        sentence = result.get_sentence()
        if not sentence:
            return

        text = sentence.get("text", "").strip()
        if not text:
            return

        is_final = "end_time" in sentence and (sentence.get("end_time") or 0) > 0

        sent_idx = sentence.get("sentence_id", id(sentence))
        if not is_final:
            if self._last_sentence_texts.get(sent_idx) == text:
                return
            self._last_sentence_texts[sent_idx] = text
        else:
            self._last_sentence_texts.pop(sent_idx, None)

        begin_time = sentence.get("begin_time") or 0
        end_time = sentence.get("end_time") or 0

        if self._on_result:
            self._on_result(TranscriptResult(
                text=text,
                is_final=is_final,
                start_ms=begin_time,
                end_ms=end_time,
            ))

    def on_complete(self) -> None:
        logger.info("Fun-ASR 转写完成")


class FunASRClient:
    """Fun-ASR 实时语音识别客户端（Recognition SDK）。"""

    def __init__(
        self,
        api_key: str,
        model: str = "fun-asr-realtime",
        language: str = "zh",
        on_result: Callable[[TranscriptResult], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_connected: Callable[[], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._language = language
        self._on_result = on_result
        self._on_error = on_error
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._recognition: Recognition | None = None
        self._connected = False

    def connect(self) -> None:
        if self._connected:
            return

        dashscope.api_key = self._api_key

        callback = _ASRCallback(
            on_result=self._on_result,
            on_error=self._on_error,
            on_connected=self._on_connected_wrapper,
            on_disconnected=self._on_disconnected_wrapper,
        )

        self._recognition = Recognition(
            model=self._model,
            format="pcm",
            sample_rate=AUDIO_SAMPLE_RATE,
            callback=callback,
            language_hints=[self._language, "en", "ja"] if self._language == "zh" else [self._language, "zh", "ja"],
        )

        try:
            self._recognition.start()
            self._connected = True
            logger.info("Fun-ASR [%s] 启动成功", self._model)
        except Exception as e:
            logger.error("Fun-ASR 启动失败: %s", e)
            if self._on_error:
                self._on_error(f"ASR 启动失败: {e}")
            self._connected = False

    def _on_connected_wrapper(self) -> None:
        self._connected = True
        if self._on_connected:
            self._on_connected()

    def _on_disconnected_wrapper(self) -> None:
        self._connected = False
        if self._on_disconnected:
            self._on_disconnected()

    def feed_audio(self, pcm_data: bytes) -> None:
        if self._recognition and self._connected:
            try:
                self._recognition.send_audio_frame(pcm_data)
            except Exception as e:
                logger.error("发送音频数据错误: %s", e)

    def disconnect(self) -> None:
        self._connected = False
        if self._recognition:
            try:
                self._recognition.stop()
            except Exception:
                pass
            self._recognition = None
        logger.info("Fun-ASR 已停止")

    @property
    def is_connected(self) -> bool:
        return self._connected


# ─────────────────────────────────────────────
# Qwen3-ASR 客户端（OmniRealtime WebSocket API）
# ─────────────────────────────────────────────

class QwenASRClient:
    """千问3 ASR 实时语音识别客户端（OmniRealtime API）。"""

    def __init__(
        self,
        api_key: str,
        model: str = "qwen3-asr-flash-realtime",
        language: str = "zh",
        on_result: Callable[[TranscriptResult], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_connected: Callable[[], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._language = language
        self._on_result = on_result
        self._on_error = on_error
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._conversation = None
        self._state = ASRState.DISCONNECTED
        self._state_lock = threading.Lock()
        self._connected_event = threading.Event()
        self._last_stash_text = ""
        self._session_start_time: float = 0.0
        self._refresh_timer: threading.Timer | None = None
        self._intentional_disconnect = False

    def connect(self) -> None:
        with self._state_lock:
            if self._state in (ASRState.CONNECTED, ASRState.CONNECTING):
                return
            self._state = ASRState.CONNECTING

        self._connected_event.clear()
        self._intentional_disconnect = False

        # 延迟导入避免未安装时影响其他功能
        from dashscope.audio.qwen_omni import (
            OmniRealtimeConversation,
            OmniRealtimeCallback,
        )
        from dashscope.audio.qwen_omni.omni_realtime import (
            TranscriptionParams,
            MultiModality,
        )

        dashscope.api_key = self._api_key
        client = self

        class _QwenCallback(OmniRealtimeCallback):
            def on_open(self) -> None:
                with client._state_lock:
                    client._state = ASRState.CONNECTED
                client._connected_event.set()
                client._session_start_time = time.monotonic()
                logger.info("Qwen3-ASR 已连接")
                if client._on_connected:
                    client._on_connected()
                # 设置会话刷新定时器
                client._schedule_session_refresh()

            def on_close(self, close_status_code, close_msg) -> None:
                with client._state_lock:
                    was_connected = client._state == ASRState.CONNECTED
                    if not client._intentional_disconnect:
                        client._state = ASRState.DISCONNECTED
                client._connected_event.clear()
                logger.info("Qwen3-ASR 已断开: code=%s, msg=%s",
                            close_status_code, close_msg)
                client._cancel_refresh_timer()
                if was_connected and not client._intentional_disconnect and client._on_disconnected:
                    client._on_disconnected()

            def on_error(self, error) -> None:
                logger.error("Qwen3-ASR WebSocket 错误: %s", error)
                with client._state_lock:
                    client._state = ASRState.ERROR
                if client._on_error:
                    client._on_error(f"ASR WebSocket 错误: {error}")

            def on_event(self, response: dict) -> None:
                try:
                    event_type = response.get("type", "")
                    now_ms = int(time.time() * 1000)

                    if event_type == "conversation.item.input_audio_transcription.completed":
                        text = response.get("transcript", "").strip()
                        if text and client._on_result:
                            client._on_result(TranscriptResult(
                                text=text, is_final=True,
                                start_ms=now_ms, end_ms=now_ms,
                            ))
                        client._last_stash_text = ""

                    elif event_type == "conversation.item.input_audio_transcription.text":
                        text = response.get("stash", "").strip()
                        if text and text != client._last_stash_text:
                            client._last_stash_text = text
                            if client._on_result:
                                client._on_result(TranscriptResult(
                                    text=text, is_final=False,
                                    start_ms=now_ms, end_ms=now_ms,
                                ))

                except Exception as e:
                    logger.error("Qwen3-ASR 事件处理错误: %s", e)

        callback = _QwenCallback()

        try:
            self._conversation = OmniRealtimeConversation(
                model=self._model,
                url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
                callback=callback,
            )
            self._conversation.connect()

            # 配置为纯 ASR 模式
            transcription_params = TranscriptionParams(
                language=self._language,
                sample_rate=AUDIO_SAMPLE_RATE,
                input_audio_format="pcm",
            )
            self._conversation.update_session(
                output_modalities=[MultiModality.TEXT],
                enable_input_audio_transcription=True,
                transcription_params=transcription_params,
            )

            logger.info("Qwen3-ASR [%s] 启动成功", self._model)
        except Exception as e:
            logger.error("Qwen3-ASR 启动失败: %s", e)
            with self._state_lock:
                self._state = ASRState.ERROR
            if self._on_error:
                self._on_error(f"ASR 启动失败: {e}")

    def _schedule_session_refresh(self) -> None:
        """在会话即将到达 120 分钟上限前主动刷新连接。"""
        self._cancel_refresh_timer()
        self._refresh_timer = threading.Timer(
            _QWEN_SESSION_MAX_SEC, self._refresh_session
        )
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def _refresh_session(self) -> None:
        """主动刷新 WebSocket 连接（断开后重连）。"""
        logger.info("Qwen3-ASR 会话接近 120 分钟上限，主动刷新连接")
        self._intentional_disconnect = True
        old_conv = self._conversation
        self._conversation = None
        if old_conv:
            try:
                old_conv.close()
            except Exception:
                pass
        with self._state_lock:
            self._state = ASRState.RECONNECTING
        self._intentional_disconnect = False
        # 重新连接
        self.connect()

    def _cancel_refresh_timer(self) -> None:
        if self._refresh_timer:
            self._refresh_timer.cancel()
            self._refresh_timer = None

    def feed_audio(self, pcm_data: bytes) -> None:
        if self._conversation and self._state == ASRState.CONNECTED:
            try:
                audio_b64 = base64.b64encode(pcm_data).decode("ascii")
                self._conversation.append_audio(audio_b64)
            except Exception as e:
                logger.error("发送音频数据错误: %s", e)

    def disconnect(self) -> None:
        self._intentional_disconnect = True
        self._cancel_refresh_timer()
        with self._state_lock:
            self._state = ASRState.DISCONNECTED
        if self._conversation:
            try:
                self._conversation.close()
            except Exception:
                pass
            self._conversation = None
        self._intentional_disconnect = False
        logger.info("Qwen3-ASR 已停止")

    @property
    def is_connected(self) -> bool:
        return self._state == ASRState.CONNECTED


# ─────────────────────────────────────────────
# 工厂函数
# ─────────────────────────────────────────────

# 模型名到客户端类的映射
_QWEN_ASR_MODELS = {"qwen3-asr-flash-realtime"}
_FUNASR_MODELS = {"fun-asr-realtime", "paraformer-realtime-v2"}


def create_asr_client(
    model: str,
    api_key: str,
    language: str = "zh",
    on_result: Callable[[TranscriptResult], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    on_connected: Callable[[], None] | None = None,
    on_disconnected: Callable[[], None] | None = None,
) -> FunASRClient | QwenASRClient:
    """根据模型名创建对应的 ASR 客户端。"""
    if model in _QWEN_ASR_MODELS:
        return QwenASRClient(
            api_key=api_key, model=model, language=language,
            on_result=on_result, on_error=on_error,
            on_connected=on_connected, on_disconnected=on_disconnected,
        )
    return FunASRClient(
        api_key=api_key, model=model, language=language,
        on_result=on_result, on_error=on_error,
        on_connected=on_connected, on_disconnected=on_disconnected,
    )
