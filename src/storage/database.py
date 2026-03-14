"""SQLite 数据库管理。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from src.storage.models import (
    ActiveQA,
    ClassSession,
    DetectedQuestion,
    SessionStatus,
    Speaker,
    SpeakerRole,
    TranscriptSegment,
)

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_name TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL,
    audio_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'stopped',
    language TEXT NOT NULL DEFAULT 'zh',
    created_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    speaker_label TEXT NOT NULL DEFAULT '',
    speaker_role TEXT NOT NULL DEFAULT 'unknown',
    text TEXT NOT NULL DEFAULT '',
    translation TEXT NOT NULL DEFAULT '',
    start_time_ms INTEGER NOT NULL DEFAULT 0,
    end_time_ms INTEGER NOT NULL DEFAULT 0,
    is_final INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS detected_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    question_text TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'auto',
    concise_answer TEXT NOT NULL DEFAULT '',
    detailed_answer TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS active_qa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    question TEXT NOT NULL DEFAULT '',
    answer TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS speakers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'unknown',
    feature_id TEXT,
    course_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


class Database:
    """SQLite 数据库封装。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def initialize(self) -> None:
        self.conn.executescript(_CREATE_TABLES_SQL)
        self.conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Sessions ──

    def create_session(self, session: ClassSession) -> int:
        cur = self.conn.execute(
            "INSERT INTO sessions (course_name, date, audio_path, status, language, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                session.course_name,
                session.date,
                session.audio_path,
                session.status.value,
                session.language,
                session.created_at.isoformat(),
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def update_session_status(self, session_id: int, status: SessionStatus) -> None:
        ended = datetime.now().isoformat() if status == SessionStatus.STOPPED else None
        self.conn.execute(
            "UPDATE sessions SET status=?, ended_at=? WHERE id=?",
            (status.value, ended, session_id),
        )
        self.conn.commit()

    def update_session_audio_path(self, session_id: int, audio_path: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET audio_path=? WHERE id=?",
            (audio_path, session_id),
        )
        self.conn.commit()

    def get_session(self, session_id: int) -> ClassSession | None:
        row = self.conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return None
        return self._row_to_session(row)

    def list_sessions(self) -> list[ClassSession]:
        rows = self.conn.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [self._row_to_session(r) for r in rows]

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> ClassSession:
        return ClassSession(
            id=row["id"],
            course_name=row["course_name"],
            date=row["date"],
            audio_path=row["audio_path"],
            status=SessionStatus(row["status"]),
            language=row["language"],
            created_at=datetime.fromisoformat(row["created_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
        )

    # ── Transcript ──

    def add_segment(self, seg: TranscriptSegment) -> int:
        cur = self.conn.execute(
            "INSERT INTO transcript_segments "
            "(session_id, speaker_label, speaker_role, text, translation, start_time_ms, end_time_ms, is_final, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                seg.session_id,
                seg.speaker_label,
                seg.speaker_role.value,
                seg.text,
                seg.translation,
                seg.start_time_ms,
                seg.end_time_ms,
                1 if seg.is_final else 0,
                seg.created_at.isoformat(),
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_segments(self, session_id: int, final_only: bool = False) -> list[TranscriptSegment]:
        sql = "SELECT * FROM transcript_segments WHERE session_id=?"
        if final_only:
            sql += " AND is_final=1"
        sql += " ORDER BY start_time_ms"
        rows = self.conn.execute(sql, (session_id,)).fetchall()
        return [
            TranscriptSegment(
                id=r["id"],
                session_id=r["session_id"],
                speaker_label=r["speaker_label"],
                speaker_role=SpeakerRole(r["speaker_role"]),
                text=r["text"],
                translation=r["translation"],
                start_time_ms=r["start_time_ms"],
                end_time_ms=r["end_time_ms"],
                is_final=bool(r["is_final"]),
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # ── Questions ──

    def add_question(self, q: DetectedQuestion) -> int:
        cur = self.conn.execute(
            "INSERT INTO detected_questions (session_id, question_text, source, concise_answer, detailed_answer, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (q.session_id, q.question_text, q.source, q.concise_answer, q.detailed_answer, q.created_at.isoformat()),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def update_question_answers(self, question_id: int, concise: str, detailed: str) -> None:
        self.conn.execute(
            "UPDATE detected_questions SET concise_answer=?, detailed_answer=? WHERE id=?",
            (concise, detailed, question_id),
        )
        self.conn.commit()

    def get_questions(self, session_id: int) -> list[DetectedQuestion]:
        rows = self.conn.execute(
            "SELECT * FROM detected_questions WHERE session_id=? ORDER BY created_at", (session_id,)
        ).fetchall()
        return [
            DetectedQuestion(
                id=r["id"],
                session_id=r["session_id"],
                question_text=r["question_text"],
                source=r["source"],
                concise_answer=r["concise_answer"],
                detailed_answer=r["detailed_answer"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # ── Active QA ──

    def add_active_qa(self, qa: ActiveQA) -> int:
        cur = self.conn.execute(
            "INSERT INTO active_qa (session_id, question, answer, created_at) VALUES (?, ?, ?, ?)",
            (qa.session_id, qa.question, qa.answer, qa.created_at.isoformat()),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_active_qas(self, session_id: int) -> list[ActiveQA]:
        rows = self.conn.execute(
            "SELECT * FROM active_qa WHERE session_id=? ORDER BY created_at", (session_id,)
        ).fetchall()
        return [
            ActiveQA(
                id=r["id"],
                session_id=r["session_id"],
                question=r["question"],
                answer=r["answer"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # ── Speakers ──

    def add_speaker(self, speaker: Speaker) -> int:
        cur = self.conn.execute(
            "INSERT INTO speakers (name, role, feature_id, course_name, created_at) VALUES (?, ?, ?, ?, ?)",
            (speaker.name, speaker.role.value, speaker.feature_id, speaker.course_name, speaker.created_at.isoformat()),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def update_speaker_feature_id(self, speaker_id: int, feature_id: str) -> None:
        self.conn.execute("UPDATE speakers SET feature_id=? WHERE id=?", (feature_id, speaker_id))
        self.conn.commit()

    def delete_speaker(self, speaker_id: int) -> None:
        self.conn.execute("DELETE FROM speakers WHERE id=?", (speaker_id,))
        self.conn.commit()

    def get_speakers_by_course(self, course_name: str) -> list[Speaker]:
        rows = self.conn.execute(
            "SELECT * FROM speakers WHERE course_name=?", (course_name,)
        ).fetchall()
        return [self._row_to_speaker(r) for r in rows]

    def get_all_speakers(self) -> list[Speaker]:
        rows = self.conn.execute("SELECT * FROM speakers ORDER BY course_name, name").fetchall()
        return [self._row_to_speaker(r) for r in rows]

    def get_teacher_feature_ids(self, course_name: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT feature_id FROM speakers WHERE course_name=? AND role='teacher' AND feature_id IS NOT NULL",
            (course_name,),
        ).fetchall()
        return [r["feature_id"] for r in rows]

    @staticmethod
    def _row_to_speaker(row: sqlite3.Row) -> Speaker:
        return Speaker(
            id=row["id"],
            name=row["name"],
            role=SpeakerRole(row["role"]),
            feature_id=row["feature_id"],
            course_name=row["course_name"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
