"""说话人管理器。"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.asr.voiceprint import VoiceprintManager
from src.storage.database import Database
from src.storage.models import Speaker, SpeakerRole

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = logging.getLogger(__name__)


class SpeakerManager:
    """管理说话人识别与声纹。"""

    def __init__(self, db: Database, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._voiceprint: VoiceprintManager | None = None
        self._speaker_label_map: dict[str, SpeakerRole] = {}

    def _get_voiceprint_manager(self) -> VoiceprintManager | None:
        if self._voiceprint is None:
            app_id = self._settings.get_api_key(self._settings.IFLYTEK_APP_ID)
            key_id = self._settings.get_api_key(self._settings.IFLYTEK_ACCESS_KEY_ID)
            key_secret = self._settings.get_api_key(self._settings.IFLYTEK_ACCESS_KEY_SECRET)
            if app_id and key_id and key_secret:
                self._voiceprint = VoiceprintManager(app_id, key_id, key_secret)
        return self._voiceprint

    def get_feature_ids(self, course_name: str) -> list[str]:
        """获取课程对应的教师声纹 ID 列表。"""
        return self._db.get_teacher_feature_ids(course_name)

    def mark_speaker_as_teacher(self, speaker_label: str) -> None:
        """将某个说话人标签标记为教师。"""
        self._speaker_label_map[speaker_label] = SpeakerRole.TEACHER

    def get_speaker_role(self, speaker_label: str) -> SpeakerRole:
        """获取说话人角色。"""
        return self._speaker_label_map.get(speaker_label, SpeakerRole.UNKNOWN)

    def register_teacher(
        self, name: str, course_name: str, audio_data: bytes
    ) -> Speaker | None:
        """注册教师声纹。"""
        vp = self._get_voiceprint_manager()
        if not vp:
            logger.error("声纹管理器未初始化")
            return None

        loop = asyncio.new_event_loop()
        try:
            feature_id = loop.run_until_complete(
                vp.register(audio_data, f"{course_name}_{name}")
            )
        finally:
            loop.close()

        if not feature_id:
            return None

        speaker = Speaker(
            name=name,
            role=SpeakerRole.TEACHER,
            feature_id=feature_id,
            course_name=course_name,
        )
        speaker.id = self._db.add_speaker(speaker)
        return speaker

    def delete_teacher(self, speaker_id: int, feature_id: str) -> bool:
        """删除教师声纹。"""
        vp = self._get_voiceprint_manager()
        if vp and feature_id:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(vp.delete(feature_id))
            finally:
                loop.close()

        self._db.delete_speaker(speaker_id)
        return True

    def get_all_speakers(self) -> list[Speaker]:
        return self._db.get_all_speakers()

    def get_speakers_by_course(self, course_name: str) -> list[Speaker]:
        return self._db.get_speakers_by_course(course_name)
