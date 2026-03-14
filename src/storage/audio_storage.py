"""音频文件存储管理。"""

from __future__ import annotations

import wave
from pathlib import Path


class AudioStorage:
    """管理课堂录音的本地存储。"""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._current_writer: wave.Wave_write | None = None
        self._current_path: Path | None = None

    def start_recording(self, session_id: int, course_name: str, date: str) -> str:
        """开始新的录音，返回音频文件路径。"""
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in course_name)
        folder = self.base_dir / f"{date}_{safe_name}"
        folder.mkdir(parents=True, exist_ok=True)
        self._current_path = folder / f"session_{session_id}.wav"

        self._current_writer = wave.open(str(self._current_path), "wb")
        self._current_writer.setnchannels(1)
        self._current_writer.setsampwidth(2)  # 16bit
        self._current_writer.setframerate(16000)

        return str(self._current_path)

    def write_chunk(self, pcm_data: bytes) -> None:
        """写入一段 PCM 数据。"""
        if self._current_writer:
            self._current_writer.writeframes(pcm_data)

    def stop_recording(self) -> str | None:
        """停止录音，返回文件路径。"""
        path = str(self._current_path) if self._current_path else None
        if self._current_writer:
            self._current_writer.close()
            self._current_writer = None
        self._current_path = None
        return path

    @property
    def is_recording(self) -> bool:
        return self._current_writer is not None
