"""数据库模型定义"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean, DateTime,
    ForeignKey, JSON, Enum, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from class_copilot.database import Base


def gen_uuid():
    return str(uuid.uuid4())


# ──────────── 课程 ────────────

class Course(Base):
    __tablename__ = "courses"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(200), nullable=False, unique=True, index=True)
    language = Column(String(10), default="zh")  # zh / en
    hot_words = Column(Text, default="")  # 逗号分隔的热词
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    sessions = relationship("Session", back_populates="course", cascade="all, delete-orphan")
    voiceprints = relationship("Voiceprint", back_populates="course", cascade="all, delete-orphan")


# ──────────── 会话 ────────────

class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    course_id = Column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    custom_name = Column(String(200), nullable=True)  # 用户自定义会话名称
    date = Column(String(10), nullable=False)  # YYYY-MM-DD
    started_at = Column(DateTime, default=datetime.now)  # active / stopped / interrupted
    refinement_status = Column(String(20), default="none")  # none / pending / in_progress / completed / partial / failed
    refinement_progress = Column(Float, default=0.0)  # 0.0 ~ 1.0
    refinement_strategy = Column(String(20), default="post")  # post / periodic / manual

    course = relationship("Course", back_populates="sessions")
    recordings = relationship("Recording", back_populates="session", cascade="all, delete-orphan")
    transcriptions = relationship("Transcription", back_populates="session", cascade="all, delete-orphan")
    questions = relationship("Question", back_populates="session", cascade="all, delete-orphan")
    chat_messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


# ──────────── 录音文件 ────────────

class Recording(Base):
    __tablename__ = "recordings"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    file_path = Column(String(500), nullable=False)
    duration_seconds = Column(Float, default=0.0)
    file_size_bytes = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.now)
    ended_at = Column(DateTime, nullable=True)
    sequence_number = Column(Integer, default=1)  # 续记时的序号

    session = relationship("Session", back_populates="recordings")


# ──────────── 转写片段 ────────────

class Transcription(Base):
    __tablename__ = "transcriptions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    recording_id = Column(String(36), ForeignKey("recordings.id", ondelete="SET NULL"), nullable=True)

    # 时间信息
    start_time = Column(Float, nullable=False)  # 相对于录音开始的秒数
    end_time = Column(Float, nullable=False)
    sequence = Column(Integer, nullable=False)  # 片段序号

    # 说话人信息
    speaker_label = Column(String(50), default="UNKNOWN")  # SPEAKER_00, TEACHER, STUDENT 等
    speaker_role = Column(String(20), default="unknown")  # teacher / student / unknown
    is_teacher = Column(Boolean, default=False)

    # 转写文本（双版本）
    realtime_text = Column(Text, nullable=False)  # 实时版本（始终保留）
    refined_text = Column(Text, nullable=True)  # 精修版本
    is_final = Column(Boolean, default=False)  # 是否为最终结果（非中间结果）

    # 精修状态
    refinement_status = Column(String(20), default="none")  # none / pending / in_progress / refined / failed
    refined_at = Column(DateTime, nullable=True)

    # 语言
    language = Column(String(10), default="zh")
    translation = Column(Text, nullable=True)  # 翻译文本

    created_at = Column(DateTime, default=datetime.now)

    session = relationship("Session", back_populates="transcriptions")

    @property
    def best_text(self):
        """返回当前最优版本的文本"""
        return self.refined_text if self.refined_text else self.realtime_text


# ──────────── 问题检测 ────────────

class Question(Base):
    __tablename__ = "questions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)

    question_text = Column(Text, nullable=False)
    source = Column(String(20), nullable=False)  # auto / manual / forced / refined
    confidence = Column(Float, default=0.0)
    context_text = Column(Text, nullable=True)  # 问题上下文

    created_at = Column(DateTime, default=datetime.now)

    session = relationship("Session", back_populates="questions")
    answers = relationship("Answer", back_populates="question", cascade="all, delete-orphan")


# ──────────── 答案 ────────────

class Answer(Base):
    __tablename__ = "answers"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    question_id = Column(String(36), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)

    answer_type = Column(String(20), nullable=False)  # brief / detailed
    content = Column(Text, nullable=False)
    language = Column(String(10), default="zh")
    is_refined_update = Column(Boolean, default=False)  # 是否基于精修文本更新
    generating = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    question = relationship("Question", back_populates="answers")

    __table_args__ = (
        UniqueConstraint("question_id", "answer_type", name="uq_question_answer_type"),
    )


# ──────────── 主动提问 ────────────

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)

    role = Column(String(20), nullable=False)  # user / assistant
    content = Column(Text, nullable=False)
    model_used = Column(String(50), nullable=True)
    think_mode = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.now)

    session = relationship("Session", back_populates="chat_messages")


# ──────────── 声纹 ────────────

class Voiceprint(Base):
    __tablename__ = "voiceprints"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    course_id = Column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    teacher_name = Column(String(100), nullable=False)
    speaker_label = Column(String(50), nullable=False)  # 云端声纹 ID
    created_at = Column(DateTime, default=datetime.now)

    course = relationship("Course", back_populates="voiceprints")


# ──────────── 精修任务 ────────────

class RefinementTask(Base):
    __tablename__ = "refinement_tasks"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    recording_id = Column(String(36), ForeignKey("recordings.id", ondelete="CASCADE"), nullable=True)

    status = Column(String(20), default="pending")  # pending / in_progress / completed / failed / cancelled
    strategy = Column(String(20), nullable=False)  # post / periodic / manual
    progress = Column(Float, default=0.0)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)

    error_message = Column(Text, nullable=True)

    audio_start_time = Column(Float, nullable=True)  # 音频片段起始时间
    audio_end_time = Column(Float, nullable=True)  # 音频片段结束时间

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    completed_at = Column(DateTime, nullable=True)


# ──────────── 设置 ────────────

class SettingItem(Base):
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    is_encrypted = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
