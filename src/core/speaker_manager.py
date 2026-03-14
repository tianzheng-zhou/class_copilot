"""说话人管理器（基于 ASR 自动分离 + 手动标记）。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.storage.database import Database
from src.storage.models import Speaker, SpeakerRole

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = logging.getLogger(__name__)


class SpeakerManager:
    """管理说话人识别（ASR 自动分离说话人，用户手动标记教师）。"""

    def __init__(self, db: Database, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._speaker_label_map: dict[str, SpeakerRole] = {}

    def mark_speaker_as_teacher(self, speaker_label: str) -> None:
        """将某个说话人标签标记为教师。"""
        self._speaker_label_map[speaker_label] = SpeakerRole.TEACHER
        logger.info("已将说话人 %s 标记为教师", speaker_label)

    def get_speaker_role(self, speaker_label: str) -> SpeakerRole:
        """获取说话人角色。"""
        return self._speaker_label_map.get(speaker_label, SpeakerRole.UNKNOWN)

    def save_teacher(self, name: str, course_name: str, speaker_label: str) -> Speaker:
        """保存教师信息到数据库。"""
        speaker = Speaker(
            name=name,
            role=SpeakerRole.TEACHER,
            course_name=course_name,
        )
        speaker.id = self._db.add_speaker(speaker)
        self._speaker_label_map[speaker_label] = SpeakerRole.TEACHER
        return speaker

    def delete_teacher(self, speaker_id: int) -> bool:
        """删除教师记录。"""
        self._db.delete_speaker(speaker_id)
        return True

    def get_all_speakers(self) -> list[Speaker]:
        return self._db.get_all_speakers()

    def get_speakers_by_course(self, course_name: str) -> list[Speaker]:
        return self._db.get_speakers_by_course(course_name)
