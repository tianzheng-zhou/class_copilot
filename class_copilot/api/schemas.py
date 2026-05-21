from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CourseCreate(BaseModel):
    name: str


class CoursePatch(BaseModel):
    name: str


class SessionPatch(BaseModel):
    custom_name: str | None = None


class SettingsPatch(BaseModel):
    dashscope_api_key: str | None = None
    language: Literal["zh", "en"] | None = None
    asr_language: Literal["zh", "en", "bilingual"] | None = None
    auto_answer_language: Literal["zh", "en", "bilingual"] | None = None
    auto_answer_model: Literal["qwen3.5-flash", "qwen3.5-plus"] | None = None
    chat_language: Literal["zh", "en", "bilingual"] | None = None
    auto_answer_type: Literal["brief", "detailed"] | None = None
    asr_model: Literal["qwen3.5-omni-flash-realtime", "qwen3.5-omni-plus-realtime"] | None = None
    chat_model_default: str | None = None
    chat_model_fast: str | None = None
    vad_threshold: float | None = None
    vad_prefix_padding_ms: int | None = None
    vad_silence_duration_ms: int | None = None
    asr_session_rotate_minutes: float | None = None
    vad_max_segment_seconds: float | None = None
    transcript_no_output_timeout_minutes: float | None = None
    question_confidence_threshold: float | None = None
    question_cooldown_seconds: int | None = None
    question_similarity_threshold: float | None = None
    audio_source: Literal["microphone", "loopback", "file"] | None = None
    audio_device_id: int | str | None = Field(default=None)
    audio_file_path: str | None = None


class WSMessage(BaseModel):
    type: str
    data: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")
