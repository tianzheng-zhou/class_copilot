from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from class_copilot.domain.exceptions import ConfigurationError
from class_copilot.infrastructure.crypto import SettingsCipher, mask_secret
from class_copilot.infrastructure.persistence.repositories import SettingsRepository


@dataclass(slots=True)
class RuntimeSettings:
    dashscope_api_key: str = ""
    language: str = "zh"
    asr_language: str = "zh"
    auto_answer_language: str = "zh"
    auto_answer_model: str = "qwen3.5-flash"
    chat_language: str = "zh"
    auto_answer_type: str = "brief"
    asr_model: str = "qwen3.5-omni-flash-realtime"
    chat_model_default: str = "qwen3.5-plus"
    chat_model_fast: str = "qwen3.5-flash"
    vad_threshold: float = 0.3
    vad_prefix_padding_ms: int = 500
    vad_silence_duration_ms: int = 800
    asr_session_rotate_minutes: float = 12.0
    vad_max_segment_seconds: float = 60.0
    transcript_no_output_timeout_minutes: float = 5.0
    question_confidence_threshold: float = 0.7
    question_cooldown_seconds: int = 15
    question_similarity_threshold: float = 0.8
    audio_source: str = "microphone"
    audio_device_id: int | str | None = None
    audio_file_path: str = ""


SETTING_TYPES: dict[str, Callable[[str], Any]] = {
    "dashscope_api_key": str,
    "language": str,
    "asr_language": str,
    "auto_answer_language": str,
    "auto_answer_model": str,
    "chat_language": str,
    "auto_answer_type": str,
    "asr_model": str,
    "chat_model_default": str,
    "chat_model_fast": str,
    "vad_threshold": float,
    "vad_prefix_padding_ms": int,
    "vad_silence_duration_ms": int,
    "asr_session_rotate_minutes": float,
    "vad_max_segment_seconds": float,
    "transcript_no_output_timeout_minutes": float,
    "question_confidence_threshold": float,
    "question_cooldown_seconds": int,
    "question_similarity_threshold": float,
    "audio_source": str,
    "audio_device_id": lambda value: None if value == "" else value,
    "audio_file_path": str,
}

ENCRYPTED_KEYS = {"dashscope_api_key"}


class SettingsService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        cipher: SettingsCipher,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cipher = cipher
        self._runtime = RuntimeSettings()
        self._listeners: list[Callable[[RuntimeSettings], None]] = []

    @property
    def runtime(self) -> RuntimeSettings:
        return self._runtime

    def add_listener(self, callback: Callable[[RuntimeSettings], None]) -> None:
        self._listeners.append(callback)

    async def load(self) -> RuntimeSettings:
        async with self._sessionmaker() as db:
            rows = await SettingsRepository(db).get_all()
        values = asdict(RuntimeSettings())
        for key, row in rows.items():
            if key not in SETTING_TYPES:
                continue
            raw = row.value
            if row.is_encrypted:
                try:
                    raw = self._cipher.decrypt(key, raw)
                except ConfigurationError:
                    logger.error("Encrypted setting cannot be decrypted: {}", key)
                    continue
            values[key] = self._parse_value(key, raw)
        if "language" in rows:
            legacy_language = values["language"]
            for key in ("asr_language", "auto_answer_language", "chat_language"):
                if key not in rows:
                    values[key] = legacy_language
        self._runtime = RuntimeSettings(**values)
        return self._runtime

    async def update(self, partial: dict[str, Any]) -> RuntimeSettings:
        if "language" in partial:
            for key in ("asr_language", "auto_answer_language", "chat_language"):
                partial.setdefault(key, partial["language"])
        clean: dict[str, Any] = {}
        for key, value in partial.items():
            if key not in SETTING_TYPES:
                raise ConfigurationError(f"unknown setting: {key}")
            clean[key] = self._validate_value(key, value)

        async with self._sessionmaker() as db:
            repo = SettingsRepository(db)
            for key, value in clean.items():
                serialized = self._serialize_value(value)
                encrypted = key in ENCRYPTED_KEYS
                if encrypted:
                    serialized = self._cipher.encrypt(serialized)
                await repo.set(key=key, value=serialized, is_encrypted=encrypted)

        await self.load()
        for listener in self._listeners:
            listener(self._runtime)
        return self._runtime

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self._runtime)
        key = self._runtime.dashscope_api_key
        data["dashscope_api_key"] = mask_secret(key)
        data["dashscope_api_key_set"] = bool(key)
        return data

    def require_api_key(self) -> str:
        if not self._runtime.dashscope_api_key:
            raise ConfigurationError("DashScope API Key 未设置")
        return self._runtime.dashscope_api_key

    def _parse_value(self, key: str, raw: str) -> Any:
        if key == "audio_device_id":
            if raw == "":
                return None
            if raw.isdigit():
                return int(raw)
            return raw
        return SETTING_TYPES[key](raw)

    def _validate_value(self, key: str, value: Any) -> Any:
        if key == "language" and value not in {"zh", "en"}:
            raise ConfigurationError("language must be zh or en")
        if key in {"asr_language", "auto_answer_language", "chat_language"} and value not in {
            "zh",
            "en",
            "bilingual",
        }:
            raise ConfigurationError(f"{key} must be zh, en, or bilingual")
        if key == "auto_answer_type" and value not in {"brief", "detailed"}:
            raise ConfigurationError("auto_answer_type must be brief or detailed")
        if key == "auto_answer_model" and value not in {"qwen3.5-flash", "qwen3.5-plus"}:
            raise ConfigurationError("auto_answer_model must be qwen3.5-flash or qwen3.5-plus")
        if key == "asr_model" and value not in {
            "qwen3.5-omni-flash-realtime",
            "qwen3.5-omni-plus-realtime",
        }:
            raise ConfigurationError("unsupported asr_model")
        if key == "audio_source" and value not in {"microphone", "loopback", "file"}:
            raise ConfigurationError("audio_source must be microphone, loopback, or file")
        if key == "audio_file_path" and value:
            return str(Path(str(value)).expanduser())
        if value is None:
            return None
        if key == "transcript_no_output_timeout_minutes":
            parsed = self._parse_value(key, str(value))
            if parsed < 0:
                raise ConfigurationError("transcript_no_output_timeout_minutes must be >= 0")
            return parsed
        return self._parse_value(key, str(value))

    def _serialize_value(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value)
