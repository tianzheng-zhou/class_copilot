"""实时 ASR 服务 - DashScope 流式语音识别"""

import asyncio
import json
from typing import Callable, Awaitable

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

from loguru import logger
from class_copilot.config import settings
from class_copilot.logger import asr_logger


class RealtimeASRCallback(RecognitionCallback):
    """实时 ASR 回调处理器"""

    def __init__(self, loop: asyncio.AbstractEventLoop, result_queue: asyncio.Queue, on_disconnect=None):
        self._loop = loop
        self._result_queue = result_queue
        self._on_disconnect = on_disconnect

    def _notify_disconnect(self, error_code=None):
        if self._on_disconnect:
            self._on_disconnect(error_code=error_code)

    def on_open(self):
        asr_logger.info("ASR 连接已建立")

    def on_close(self):
        asr_logger.info("ASR 连接已关闭")
        self._notify_disconnect(error_code=None)

    def on_event(self, result: RecognitionResult):
        """收到识别结果"""
        try:
            sentence = result.get_sentence()
            if sentence is None:
                return

            text = sentence.get("text", "")
            end_time = sentence.get("end_time")
            is_final = end_time is not None and end_time >= 0

            begin_time = sentence.get("begin_time") or 0
            end_time_val = end_time if (is_final and end_time) else 0

            msg = {
                "text": text,
                "is_final": is_final,
                "start_time": begin_time / 1000.0,
                "end_time": end_time_val / 1000.0,
                "speaker_label": "UNKNOWN",
                "sentence_id": sentence.get("sentence_id", 0),
            }

            # 部分模型支持说话人分离，尝试获取
            try:
                stash = result.get_stash()
                if stash:
                    speaker_id = stash.get("speaker_id")
                    if speaker_id is not None:
                        msg["speaker_label"] = f"SPEAKER_{speaker_id}"
            except Exception:
                pass

            if text.strip():
                asr_logger.debug("ASR结果 [final={}]: {}", is_final, text)
                self._loop.call_soon_threadsafe(self._result_queue.put_nowait, msg)

        except Exception as e:
            asr_logger.error("处理ASR结果异常: {}", e)

    def on_error(self, result: RecognitionResult):
        asr_logger.error("ASR 错误: {}", result)
        # 提取错误码传给 disconnect 回调
        error_code = None
        try:
            import json
            err = json.loads(str(result))
            error_code = err.get("status_code") or err.get("code")
        except Exception:
            pass
        self._notify_disconnect(error_code=error_code)

    def on_complete(self):
        asr_logger.info("ASR 识别完成")
        self._notify_disconnect(error_code=None)


class RealtimeASRService:
    """实时 ASR 管理"""

    def __init__(self):
        self._recognition = None
        self._callback = None
        self.result_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._disconnected = False  # ASR 服务端断开标志
        self._last_error_code: int | None = None  # 最近一次错误码

    async def start(self, hot_words: str = "", language: str = "zh"):
        """启动实时 ASR"""
        if self._running:
            asr_logger.warning("ASR 已在运行中")
            return

        loop = asyncio.get_event_loop()
        self._callback = RealtimeASRCallback(loop, self.result_queue, on_disconnect=self._on_asr_disconnect)

        # 构建热词参数
        vocabulary = None
        if hot_words:
            words = [w.strip() for w in hot_words.split(",") if w.strip()]
            if words:
                vocabulary = [{"text": w, "weight": 4} for w in words]

        # 语言映射
        lang_map = {"zh": "zh", "en": "en"}

        dashscope.api_key = settings.dashscope_api_key

        self._recognition = Recognition(
            model=settings.asr_model,
            format="pcm",
            sample_rate=settings.sample_rate,
            callback=self._callback,
            language_hints=[lang_map.get(language, "zh")],
            disfluency_removal_enabled=True,
            # 说话人分离
            **({
                "vocabulary": vocabulary,
            } if vocabulary else {}),
        )

        self._recognition.start()
        self._running = True
        self._disconnected = False
        asr_logger.info("实时 ASR 已启动, 模型={}, 语言={}", settings.asr_model, language)

    async def send_audio(self, audio_bytes: bytes):
        """发送音频数据到 ASR"""
        if self._recognition and self._running and not self._disconnected:
            try:
                self._recognition.send_audio_frame(audio_bytes)
            except Exception as e:
                if not self._disconnected:
                    self._disconnected = True
                    asr_logger.error("ASR 连接已断开，停止发送音频: {}", e)

    async def stop(self):
        """停止 ASR"""
        if self._recognition and self._running:
            try:
                self._recognition.stop()
            except Exception as e:
                if not self._disconnected:
                    asr_logger.error("停止ASR异常: {}", e)
            finally:
                self._running = False
                self._disconnected = False
                self._recognition = None
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
