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

    def __init__(self, loop: asyncio.AbstractEventLoop, result_queue: asyncio.Queue):
        self._loop = loop
        self._result_queue = result_queue

    def on_open(self):
        asr_logger.info("ASR 连接已建立")

    def on_close(self):
        asr_logger.info("ASR 连接已关闭")

    def on_event(self, result: RecognitionResult):
        """收到识别结果"""
        try:
            sentence = result.get_sentence()
            if sentence is None:
                return

            text = sentence.get("text", "")
            is_final = sentence.get("end_time", -1) >= 0  # 有 end_time 说明是最终结果

            # 说话人信息
            stash = result.get_stash()
            speaker_id = None
            if stash:
                speaker_id = stash.get("speaker_id")

            msg = {
                "text": text,
                "is_final": is_final,
                "start_time": sentence.get("begin_time", 0) / 1000.0,
                "end_time": sentence.get("end_time", 0) / 1000.0 if is_final else 0,
                "speaker_label": f"SPEAKER_{speaker_id}" if speaker_id is not None else "UNKNOWN",
                "sentence_id": sentence.get("sentence_id", 0),
            }

            if text.strip():
                asr_logger.debug("ASR结果 [final={}] [spk={}]: {}", is_final, msg["speaker_label"], text)
                self._loop.call_soon_threadsafe(self._result_queue.put_nowait, msg)

        except Exception as e:
            asr_logger.error("处理ASR结果异常: {}", e)

    def on_error(self, result: RecognitionResult):
        asr_logger.error("ASR 错误: {}", result)

    def on_complete(self):
        asr_logger.info("ASR 识别完成")


class RealtimeASRService:
    """实时 ASR 管理"""

    def __init__(self):
        self._recognition = None
        self._callback = None
        self.result_queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    async def start(self, hot_words: str = "", language: str = "zh"):
        """启动实时 ASR"""
        if self._running:
            asr_logger.warning("ASR 已在运行中")
            return

        loop = asyncio.get_event_loop()
        self._callback = RealtimeASRCallback(loop, self.result_queue)

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
        asr_logger.info("实时 ASR 已启动, 模型={}, 语言={}", settings.asr_model, language)

    async def send_audio(self, audio_bytes: bytes):
        """发送音频数据到 ASR"""
        if self._recognition and self._running:
            try:
                self._recognition.send_audio_frame(audio_bytes)
            except Exception as e:
                asr_logger.error("发送音频到ASR失败: {}", e)

    async def stop(self):
        """停止 ASR"""
        if self._recognition and self._running:
            try:
                self._recognition.stop()
            except Exception as e:
                asr_logger.error("停止ASR异常: {}", e)
            finally:
                self._running = False
                self._recognition = None
                asr_logger.info("实时 ASR 已停止")

    @property
    def is_running(self) -> bool:
        return self._running
