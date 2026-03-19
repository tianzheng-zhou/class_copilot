"""音频采集服务 - 使用 sounddevice 采集并编码为 MP3"""

import asyncio
import time
from pathlib import Path
from datetime import datetime

import numpy as np
import sounddevice as sd
import lameenc

from loguru import logger

from class_copilot.config import settings
from class_copilot.logger import asr_logger


class AudioService:
    """音频采集与录音管理"""

    def __init__(self):
        self.is_recording = False
        self.sample_rate = settings.sample_rate
        self.channels = settings.channels
        self.audio_queue: asyncio.Queue = asyncio.Queue()
        self.mp3_encoder = None
        self.mp3_file = None
        self.mp3_path: str | None = None
        self._stream = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._start_time: float = 0
        self._device_index: int | None = None

    def list_devices(self) -> list[dict]:
        """列出所有可用的音频输入设备"""
        devices = sd.query_devices()
        input_devices = []
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                input_devices.append({
                    "index": i,
                    "name": d["name"],
                    "channels": d["max_input_channels"],
                    "sample_rate": d["default_samplerate"],
                    "is_default": i == sd.default.device[0],
                })
        return input_devices

    def set_device(self, device_index: int | None):
        """设置音频输入设备"""
        self._device_index = device_index
        logger.info("设置音频设备: {}", device_index)

    async def start_recording(self, session_id: str, sequence: int = 1) -> str:
        """开始录音，返回 MP3 文件路径"""
        if self.is_recording:
            logger.warning("已在录音中，忽略重复启动")
            return self.mp3_path

        self._loop = asyncio.get_event_loop()

        # 创建 MP3 文件
        recordings_dir = Path(settings.data_dir) / "recordings"
        recordings_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.mp3_path = str(recordings_dir / f"{session_id}_{date_str}_{sequence}.mp3")

        # 初始化 MP3 编码器
        self.mp3_encoder = lameenc.Encoder()
        self.mp3_encoder.set_bit_rate(128)
        self.mp3_encoder.set_in_sample_rate(self.sample_rate)
        self.mp3_encoder.set_channels(self.channels)
        self.mp3_encoder.set_quality(2)
        self.mp3_file = open(self.mp3_path, "wb")

        self._start_time = time.time()
        self.is_recording = True

        # 开启音频流
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=int(self.sample_rate * 0.1),  # 100ms 块
            device=self._device_index,
            callback=self._audio_callback,
        )
        self._stream.start()
        asr_logger.info("录音开始: {}", self.mp3_path)
        return self.mp3_path

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status):
        """音频流回调（在音频线程中运行）"""
        if status:
            asr_logger.warning("音频流状态: {}", status)

        audio_bytes = indata.tobytes()

        # 写入 MP3（同步，在音频线程中执行）
        if self.mp3_encoder and self.mp3_file:
            mp3_data = self.mp3_encoder.encode(audio_bytes)
            if mp3_data:
                self.mp3_file.write(mp3_data)
                self.mp3_file.flush()

        # 将音频数据推送到队列供 ASR 使用
        if self._loop and self.is_recording:
            try:
                self._loop.call_soon_threadsafe(self.audio_queue.put_nowait, audio_bytes)
            except asyncio.QueueFull:
                pass  # 队列满时丢弃

    async def stop_recording(self) -> dict:
        """停止录音，返回录音信息"""
        if not self.is_recording:
            return {}

        self.is_recording = False

        # 停止音频流
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        # 刷新 MP3 编码器
        if self.mp3_encoder and self.mp3_file:
            remaining = self.mp3_encoder.flush()
            if remaining:
                self.mp3_file.write(remaining)
            self.mp3_file.close()
            self.mp3_file = None

        duration = time.time() - self._start_time
        file_size = Path(self.mp3_path).stat().st_size if self.mp3_path else 0

        asr_logger.info("录音停止: 时长={:.1f}s 大小={:.1f}MB", duration, file_size / 1024 / 1024)

        return {
            "file_path": self.mp3_path,
            "duration_seconds": duration,
            "file_size_bytes": file_size,
        }

    @property
    def elapsed_seconds(self) -> float:
        """录音已进行的时间"""
        if self.is_recording:
            return time.time() - self._start_time
        return 0
