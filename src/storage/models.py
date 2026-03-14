"""数据模型定义。"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class SpeakerRole(enum.Enum):
    UNKNOWN = "unknown"
    TEACHER = "teacher"
    STUDENT = "student"


class AnswerMode(enum.Enum):
    CONCISE = "concise"
    DETAILED = "detailed"


class LLMFilterMode(enum.Enum):
    TEACHER_ONLY = "teacher_only"
    ALL = "all"


class SessionStatus(enum.Enum):
    RECORDING = "recording"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass
class Speaker:
    """说话人信息。"""
    id: int | None = None
    name: str = ""
    role: SpeakerRole = SpeakerRole.UNKNOWN
    feature_id: str | None = None  # 讯飞声纹 ID
    course_name: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class TranscriptSegment:
    """转写片段。"""
    id: int | None = None
    session_id: int = 0
    speaker_label: str = ""  # ASR 返回的说话人标签
    speaker_role: SpeakerRole = SpeakerRole.UNKNOWN
    text: str = ""
    translation: str = ""  # 英文授课时的中文翻译
    start_time_ms: int = 0
    end_time_ms: int = 0
    is_final: bool = False
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class DetectedQuestion:
    """检测出的问题。"""
    id: int | None = None
    session_id: int = 0
    question_text: str = ""
    source: str = "auto"  # auto / manual
    concise_answer: str = ""
    detailed_answer: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ActiveQA:
    """用户主动提问记录。"""
    id: int | None = None
    session_id: int = 0
    question: str = ""
    answer: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ClassSession:
    """课堂会话。"""
    id: int | None = None
    course_name: str = ""
    date: str = ""
    audio_path: str = ""
    status: SessionStatus = SessionStatus.STOPPED
    language: str = "zh"  # zh / en
    created_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None
