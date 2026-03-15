"""音频文件存储管理（MP3 格式，流式编码）。"""

from __future__ import annotations

import time
from io import BufferedWriter
from pathlib import Path
from typing import IO

import lameenc

_MP3_BITRATE = 64   # kbps，对语音已足够清晰，约 28 MB/小时
_SAMPLE_RATE = 16000


class AudioStorage:
    """管理课堂录音的本地存储（MP3 流式写入）。"""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._encoder: lameenc.Encoder | None = None
        self._file: BufferedWriter | None = None
        self._current_path: Path | None = None

    def _open_mp3(self, path: Path) -> None:
        """初始化 LAME 编码器并打开输出文件。"""
        enc = lameenc.Encoder()
        enc.set_bit_rate(_MP3_BITRATE)
        enc.set_in_sample_rate(_SAMPLE_RATE)
        enc.set_channels(1)
        enc.set_quality(5)  # 2=最高质量，7=最快，5 为均衡
        self._encoder = enc
        self._file = open(path, "wb")
        self._current_path = path

    def start_recording(self, session_id: int, course_name: str, date: str) -> str:
        """开始新的录音，返回音频文件路径。"""
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in course_name)
        folder = self.base_dir / f"{date}_{safe_name}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"session_{session_id}.mp3"
        self._open_mp3(path)
        return str(path)

    def start_recording_continuation(self, session_id: int, course_name: str, date: str) -> str:
        """续录：在原 session 文件夹下创建新分段文件。"""
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in course_name)
        folder = self.base_dir / f"{date}_{safe_name}"
        folder.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        path = folder / f"session_{session_id}_resume_{ts}.mp3"
        self._open_mp3(path)
        return str(path)

    def write_chunk(self, pcm_data: bytes) -> None:
        """将 PCM 数据编码为 MP3 并追加写入文件。"""
        if self._encoder and self._file:
            mp3_bytes = self._encoder.encode(pcm_data)
            if mp3_bytes:
                self._file.write(mp3_bytes)

    def stop_recording(self) -> str | None:
        """停止录音，刷新编码器缓冲并关闭文件，返回文件路径。"""
        path = str(self._current_path) if self._current_path else None
        if self._encoder and self._file:
            tail = self._encoder.flush()
            if tail:
                self._file.write(tail)
            self._file.close()
        self._encoder = None
        self._file = None
        self._current_path = None
        return path

    @property
    def is_recording(self) -> bool:
        return self._encoder is not None
