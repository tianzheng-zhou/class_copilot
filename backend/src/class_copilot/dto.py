"""Public DTOs are the source of generated web types."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from .domain import Settings


class Entity(BaseModel):
    id: str
    revision: int
    created_at: str
    updated_at: str


class Error(BaseModel):
    code: str
    message: str
    retryable: bool
    details: dict[str, Any]


class Resource(BaseModel):
    type: str
    id: str


class Progress(BaseModel):
    phase: str
    completed: int
    total: int | None
    unit: str
    latency_ms: int | None = None
    duplicate_ids: list[str] = Field(default_factory=list)


class Job(Entity):
    kind: str
    state: str
    lesson_id: str | None
    source_id: str | None
    parent_id: str | None
    retry_of: str | None
    resource: Resource | None
    progress: Progress
    started_at: str | None
    finished_at: str | None
    cancel_requested: bool
    error: Error | None


class Course(Entity):
    name: str
    lesson_count: int


class Lesson(Entity):
    course_id: str
    course_name: str
    custom_title: str | None
    display_title: str
    lifecycle: str
    automation_mode: Literal["auto_answer", "detect_only", "transcribe_only"]
    automation_revision: int
    content_revision: int
    source_count: int
    transcript_count: int
    question_count: int
    active_jobs: list[Job]
    audio_activity: str | None
    latest_summary_id: str | None


class Gap(BaseModel):
    start_ms: int
    end_ms: int
    reason: str
    source_id: str | None = None


class Asset(Entity):
    source_id: str
    role: str
    bytes: int
    duration_ms: int
    mime_type: str
    state: str
    url: str


class Source(Entity):
    lesson_id: str
    ordinal: int
    kind: str
    device_label: str | None
    original_filename: str | None
    capture_state: str
    transcription_state: str
    settings_revision: int
    started_at: str | None
    stopped_at: str | None
    stop_at: str | None
    duration_ms: int
    captured_ms: int
    transcribed_ms: int
    gap_ranges: list[Gap]
    assets: list[Asset]
    active_job_ids: list[str]
    error: Error | None


class Transcript(Entity):
    lesson_id: str
    source_id: str
    source_ordinal: int
    ordinal: int
    start_ms: int
    end_ms: int
    text: str
    model: str


class SourceRange(BaseModel):
    source_id: str
    start_ordinal: int
    end_ordinal: int
    start_ms: int
    end_ms: int


class Coverage(BaseModel):
    source_ranges: list[SourceRange]
    chat_turn_ids: list[str]
    answer_version_ids: list[str]
    gaps: list[Gap]
    truncated: bool
    description: str


class Generation(Entity):
    content: str
    state: str
    model: str
    job_id: str
    basis_revision: int
    context_coverage: Coverage
    error: Error | None
    finished_at: str | None


class Answer(Generation):
    question_id: str
    version: int
    style: str
    language: str


class Question(Entity):
    lesson_id: str
    text: str
    origin: str
    segment_ids: list[str]
    confidence: float | None
    answer_versions: list[Answer]


class ChatReply(Generation):
    turn_id: str
    attempt: int
    thinking: bool


class ChatTurn(Entity):
    lesson_id: str
    ordinal: int
    user_content: str
    replies: list[ChatReply]
    selected_reply_id: str | None


class Summary(Generation):
    lesson_id: str
    version: int
    include_chat: bool
    language: str
    content_signature: str
    is_stale: bool


class PublicTypes(BaseModel):
    course: Course
    lesson: Lesson
    source: Source
    transcript: Transcript
    question: Question
    answer: Answer
    chat_turn: ChatTurn
    summary: Summary
    job: Job


class Meta(BaseModel):
    request_id: str


class Envelope[T](BaseModel):
    data: T
    meta: Meta


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None
    total: int


class Accepted(BaseModel):
    job: Job
    resource: Resource | None


class SourceStop(BaseModel):
    source: Source
    job: Job | None


class SegmentPage(Page[Transcript]):
    gaps: list[Gap]


class Snapshot(BaseModel):
    lesson: Lesson
    sources: Page[Source]
    transcripts: Page[Transcript]
    questions: Page[Question]
    chat_turns: Page[ChatTurn]
    summaries: Page[Summary]
    active_jobs: list[Job]
    event_cursor: str


class Credential(BaseModel):
    id: str
    set: bool
    masked_value: str | None
    revision: int


class Health(BaseModel):
    version: str
    ready: bool


class Bootstrap(BaseModel):
    csrf_token: str
    configured: bool
    active_audio: Job | None
    capabilities: dict[str, dict[str, bool]]
    event_cursor: str


class Device(BaseModel):
    id: str
    label: str
    kind: str
    is_default: bool = False


class Devices(BaseModel):
    devices: list[Device]
    unavailable_reason: str | None


class Command(BaseModel):
    response_status: int
    response_body: Any
    expires_at: str


class RequestError(Error):
    request_id: str


class ErrorEnvelope(BaseModel):
    error: RequestError


class PublicSettings(Settings):
    id: str
    revision: int
    effective: dict[str, str]
