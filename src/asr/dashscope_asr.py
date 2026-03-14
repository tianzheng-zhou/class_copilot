"""阿里云百炼 DashScope 实时语音识别客户端。

支持两种 ASR 模型：
- fun-asr-realtime: 使用 Recognition SDK，课堂/演讲场景优化
- qwen3-asr-flash-realtime: 使用 OmniRealtime WebSocket API，多语种高精度
"""

from __future__ import annotations

import base64
import logging
import threading
from typing import Callable, Protocol

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

from src.config.constants import AUDIO_SAMPLE_RATE

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
        on_result: Callable[[TranscriptResult], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_connected: Callable[[], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
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
            language_hints=["zh", "en", "ja"],
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
        on_result: Callable[[TranscriptResult], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_connected: Callable[[], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._on_result = on_result
        self._on_error = on_error
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._conversation = None
        self._connected = False
        self._last_stash_text = ""

    def connect(self) -> None:
        if self._connected:
            return

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
                client._connected = True
                logger.info("Qwen3-ASR 已连接")
                if client._on_connected:
                    client._on_connected()

            def on_close(self, close_status_code, close_msg) -> None:
                was_connected = client._connected
                client._connected = False
                logger.info("Qwen3-ASR 已断开: code=%s, msg=%s",
                            close_status_code, close_msg)
                if was_connected and client._on_disconnected:
                    client._on_disconnected()

            def on_event(self, response: dict) -> None:
                try:
                    event_type = response.get("type", "")

                    if event_type == "conversation.item.input_audio_transcription.completed":
                        # 最终结果
                        text = response.get("transcript", "").strip()
                        if text and client._on_result:
                            client._on_result(TranscriptResult(
                                text=text, is_final=True,
                            ))
                        client._last_stash_text = ""

                    elif event_type == "conversation.item.input_audio_transcription.text":
                        # 中间结果
                        text = response.get("stash", "").strip()
                        if text and text != client._last_stash_text:
                            client._last_stash_text = text
                            if client._on_result:
                                client._on_result(TranscriptResult(
                                    text=text, is_final=False,
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
                language="zh",
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
            if self._on_error:
                self._on_error(f"ASR 启动失败: {e}")
            self._connected = False

    def feed_audio(self, pcm_data: bytes) -> None:
        if self._conversation and self._connected:
            try:
                audio_b64 = base64.b64encode(pcm_data).decode("ascii")
                self._conversation.append_audio(audio_b64)
            except Exception as e:
                logger.error("发送音频数据错误: %s", e)

    def disconnect(self) -> None:
        self._connected = False
        if self._conversation:
            try:
                self._conversation.close()
            except Exception:
                pass
            self._conversation = None
        logger.info("Qwen3-ASR 已停止")

    @property
    def is_connected(self) -> bool:
        return self._connected


# ─────────────────────────────────────────────
# 工厂函数
# ─────────────────────────────────────────────

# 模型名到客户端类的映射
_QWEN_ASR_MODELS = {"qwen3-asr-flash-realtime"}
_FUNASR_MODELS = {"fun-asr-realtime", "paraformer-realtime-v2"}


def create_asr_client(
    model: str,
    api_key: str,
    on_result: Callable[[TranscriptResult], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    on_connected: Callable[[], None] | None = None,
    on_disconnected: Callable[[], None] | None = None,
) -> FunASRClient | QwenASRClient:
    """根据模型名创建对应的 ASR 客户端。"""
    if model in _QWEN_ASR_MODELS:
        return QwenASRClient(
            api_key=api_key, model=model,
            on_result=on_result, on_error=on_error,
            on_connected=on_connected, on_disconnected=on_disconnected,
        )
    return FunASRClient(
        api_key=api_key, model=model,
        on_result=on_result, on_error=on_error,
        on_connected=on_connected, on_disconnected=on_disconnected,
    )
