"""转写管理器。"""

from __future__ import annotations

import logging
from datetime import datetime

from src.storage.database import Database
from src.storage.models import SpeakerRole, TranscriptSegment

logger = logging.getLogger(__name__)


class TranscriptManager:
    """管理实时转写文本。"""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._segments: list[TranscriptSegment] = []
        self._current_session_id: int | None = None

    def set_session(self, session_id: int) -> None:
        self._current_session_id = session_id
        self._segments.clear()

    def load_from_db(self, session_id: int) -> None:
        """从数据库恢复历史片段到内存（用于还原 LLM 上下文）。"""
        self._segments = self._db.get_segments(session_id, final_only=True)
        self._current_session_id = session_id

    def add_segment(self, seg: TranscriptSegment) -> TranscriptSegment:
        """添加转写片段，仅持久化最终结果。"""
        if self._current_session_id:
            seg.session_id = self._current_session_id
        if seg.is_final:
            seg.id = self._db.add_segment(seg)
            self._segments.append(seg)
        return seg

    def get_context_text(self, max_chars: int = 3000, teacher_only: bool = True) -> str:
        """获取上下文文本。"""
        parts = []
        total = 0
        for seg in reversed(self._segments):
            if teacher_only and seg.speaker_role != SpeakerRole.TEACHER:
                continue
            if not seg.is_final:
                continue
            text = seg.text
            if total + len(text) > max_chars:
                break
            parts.insert(0, text)
            total += len(text)
        return "\n".join(parts)

    def get_recent_text(self, n_segments: int = 5) -> str:
        """获取最近几段转写文本。"""
        recent = [s for s in self._segments if s.is_final][-n_segments:]
        return "\n".join(s.text for s in recent)

    def get_all_segments(self) -> list[TranscriptSegment]:
        return list(self._segments)

    def clear(self) -> None:
        self._segments.clear()
        self._current_session_id = None
