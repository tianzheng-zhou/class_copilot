"""麦克风音频采集。"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import pyaudio

from src.config.constants import (
    AUDIO_CHANNELS,
    AUDIO_CHUNK_BYTES,
    AUDIO_SAMPLE_RATE,
    AUDIO_SAMPLE_WIDTH,
)

logger = logging.getLogger(__name__)


class AudioCapture:
    """从麦克风实时采集 PCM 音频数据。"""

    def __init__(
        self,
        device_index: int = -1,
        on_audio_chunk: Callable[[bytes], None] | None = None,
    ) -> None:
        self._device_index = device_index if device_index >= 0 else None
        self._on_audio_chunk = on_audio_chunk
        self._pa: pyaudio.PyAudio | None = None
        self._stream: pyaudio.Stream | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    @staticmethod
    def list_devices() -> list[dict]:
        """列出可用的音频输入设备。"""
        pa = pyaudio.PyAudio()
        devices = []
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                devices.append({
                    "index": i,
                    "name": info["name"],
                    "channels": info["maxInputChannels"],
                    "sample_rate": info["defaultSampleRate"],
                })
        pa.terminate()
        return devices

    def start(self) -> None:
        if self._running:
            return

        self._pa = pyaudio.PyAudio()
        kwargs = {
            "format": pyaudio.paInt16,
            "channels": AUDIO_CHANNELS,
            "rate": AUDIO_SAMPLE_RATE,
            "input": True,
            "frames_per_buffer": AUDIO_CHUNK_BYTES // AUDIO_SAMPLE_WIDTH,
        }
        if self._device_index is not None:
            kwargs["input_device_index"] = self._device_index

        self._stream = self._pa.open(**kwargs)
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("音频采集已启动")

    def _capture_loop(self) -> None:
        while self._running and self._stream:
            try:
                data = self._stream.read(
                    AUDIO_CHUNK_BYTES // AUDIO_SAMPLE_WIDTH,
                    exception_on_overflow=False,
                )
                if self._on_audio_chunk:
                    self._on_audio_chunk(data)
            except OSError as e:
                logger.error("音频采集错误: %s", e)
                break

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
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa:
            self._pa.terminate()
            self._pa = None
        logger.info("音频采集已停止")

    @property
    def is_running(self) -> bool:
        return self._running
