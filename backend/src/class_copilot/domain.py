from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Mode = Literal["auto_answer", "detect_only", "transcribe_only"]
Language = Literal["zh", "en", "bilingual"]
Role = Literal["fast", "quality"]
Kind = Literal["microphone", "loopback"]
ACTIVE = ("queued", "running", "cancelling")
TERMINAL = ("succeeded", "failed", "cancelled", "interrupted")


def now():
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def uid():
    return str(uuid4())


def normalize(text):
    return unicodedata.normalize("NFKC", text).strip().casefold()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Fault(Exception):
    def __init__(self, code, message, status=409, retryable=False, **details):
        self.code, self.message, self.status = code, message, status
        self.retryable, self.details = retryable, details

    def public(self):
        return dict(code=self.code, message=self.message, retryable=self.retryable, details=self.details)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def explicit_nulls(cls, value):
        nullable = {"custom_title", "auto_stop_minutes", "default_device_id"}
        if isinstance(value, dict):
            for key, item in value.items():
                if item is None and key not in nullable:
                    raise ValueError(f"{key} does not accept null; omit it to use the default")
        return value


class Empty(Strict):
    pass


Name = Annotated[str, Field(min_length=1, max_length=100)]
Title = Annotated[str, Field(min_length=1, max_length=200)]
Minutes = Annotated[int, Field(ge=1, le=240)]


class CourseInput(Strict):
    name: Name


class LessonInput(Strict):
    course_id: str
    custom_title: Title | None = None
    automation_mode: Mode | None = None

    @field_validator("course_id")
    @classmethod
    def valid_id(cls, v):
        return str(UUID(v))


class LessonPatch(Strict):
    custom_title: Title | None = None


class Automation(Strict):
    mode: Mode


class Recording(Strict):
    kind: Kind
    device_id: Annotated[str, Field(min_length=1, max_length=300)]
    auto_stop_minutes: Minutes | None = None


class SourcePatch(Strict):
    auto_stop_minutes: Minutes | None


class AudioTest(Strict):
    kind: Kind
    device_id: str


class Analysis(Strict):
    generate_summary: bool = True
    include_chat_in_summary: bool = False


class Selection(Strict):
    segment_ids: Annotated[list[str], Field(min_length=1, max_length=100)]


class AnswerInput(Strict):
    style: Literal["brief", "detailed"] | None = None
    language: Language | None = None
    model_role: Role | None = None


class DirectAnswer(AnswerInput, Selection):
    pass


class ReplyInput(Strict):
    model_role: Role = "fast"
    thinking: bool = False


class ChatInput(ReplyInput):
    content: Annotated[str, Field(min_length=1, max_length=20000)]


class SummaryInput(Strict):
    include_chat: bool = False
    language: Language | None = None
    model_role: Role | None = None


class CredentialInput(Strict):
    api_key: Annotated[str, Field(min_length=1, max_length=4096)]


class ProviderTest(Strict):
    capability: Literal["transcription", "text"]
    model_role: Role | None = None


class ProviderSettings(Strict):
    region: str = ""
    base_url: str = ""

    @field_validator("base_url")
    @classmethod
    def allowed_url(cls, v):
        if not v:
            return v
        p = urlsplit(v)
        host = p.hostname or ""
        allowed = host in {
            "dashscope.aliyuncs.com",
            "dashscope-intl.aliyuncs.com",
            "dashscope-us.aliyuncs.com",
        } or host.endswith(".maas.aliyuncs.com")
        if (
            p.scheme != "https"
            or not allowed
            or p.username
            or p.password
            or p.query
            or p.fragment
            or p.port not in (None, 443)
            or p.path.rstrip("/") != "/compatible-mode/v1"
        ):
            raise ValueError("Use an HTTPS Bailian compatible-mode/v1 workspace address")
        return v.rstrip("/")


class Models(Strict):
    transcription: Literal["qwen3.8-omni-flash"] = "qwen3.8-omni-flash"
    detection: str = "qwen3.8-flash"
    answer: str = "qwen3.8-flash"
    chat_fast: str = "qwen3.8-flash"
    chat_quality: str = "qwen3.8-max"
    summary: str = "qwen3.8-flash"

    @field_validator("detection", "answer", "chat_fast", "chat_quality", "summary")
    @classmethod
    def supported(cls, v):
        if v not in ("qwen3.8-flash", "qwen3.8-max"):
            raise ValueError("Supported text models: qwen3.8-flash, qwen3.8-max")
        return v


class TranscriptionSettings(Strict):
    language: Literal["zh", "en", "mixed"] = "mixed"
    max_chunk_seconds: Annotated[int, Field(ge=4, le=30)] = 12
    silence_ms: Annotated[int, Field(ge=200, le=2000)] = 600


class AutomationSettings(Strict):
    default_mode: Mode = "auto_answer"


class DetectionSettings(Strict):
    confidence_threshold: Annotated[float, Field(ge=0, le=1)] = 0.7
    cooldown_seconds: Annotated[int, Field(ge=0, le=120)] = 10
    dedup_window_seconds: Annotated[int, Field(ge=0, le=3600)] = 300


class GenerationSettings(Strict):
    default_style: Literal["brief", "detailed"] = "brief"
    language: Language = "zh"


class AudioSettings(Strict):
    default_kind: Kind = "microphone"
    default_device_id: str | None = None
    auto_stop_minutes: Minutes | None = None


class Settings(Strict):
    provider: ProviderSettings = Field(default_factory=ProviderSettings)
    models: Models = Field(default_factory=Models)
    transcription: TranscriptionSettings = Field(default_factory=TranscriptionSettings)
    automation: AutomationSettings = Field(default_factory=AutomationSettings)
    detection: DetectionSettings = Field(default_factory=DetectionSettings)
    generation: GenerationSettings = Field(default_factory=GenerationSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)


def merge(base, patch):
    result = dict(base)
    for key, value in patch.items():
        result[key] = (
            merge(base[key], value) if isinstance(value, dict) and isinstance(base.get(key), dict) else value
        )
    return result


class DetectedQuestion(Strict):
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    confidence: Annotated[float, Field(ge=0, le=1)]


class DetectionResult(Strict):
    questions: Annotated[list[DetectedQuestion], Field(max_length=20)]
