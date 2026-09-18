"""Short SQLAlchemy transactions; relational constraints with versioned JSON payloads."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import (
    JSON,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    event,
    select,
    text,
)

from .domain import Fault, Settings, now, uid

metadata = MetaData()
tables = {}
relations = {
    "courses": [],
    "lessons": [("course_id", "courses")],
    "audio_sources": [("lesson_id", "lessons")],
    "audio_assets": [("source_id", "audio_sources")],
    "audio_chunks": [("source_id", "audio_sources")],
    "transcript_segments": [
        ("lesson_id", "lessons"),
        ("source_id", "audio_sources"),
        ("chunk_id", "audio_chunks"),
    ],
    "questions": [("lesson_id", "lessons")],
    "answer_versions": [("question_id", "questions")],
    "chat_turns": [("lesson_id", "lessons")],
    "chat_replies": [("turn_id", "chat_turns")],
    "summary_versions": [("lesson_id", "lessons")],
    "jobs": [],
    "settings": [],
    "credentials": [],
    "idempotency_keys": [],
}
for name, refs in relations.items():
    columns = [Column("id", String, primary_key=True), Column("data", JSON, nullable=False)]
    for key, parent in refs:
        columns.append(
            Column(
                key,
                String,
                ForeignKey(f"{parent}.id", ondelete="RESTRICT" if parent == "courses" else "CASCADE"),
                nullable=False,
                index=True,
            )
        )
    if name == "courses":
        columns.append(Column("normalized_name", String, unique=True, nullable=False))
    if name in ("audio_sources", "audio_chunks", "chat_turns"):
        columns.append(Column("ordinal", Integer, nullable=False))
        columns.append(UniqueConstraint(refs[0][0], "ordinal"))
    if name == "transcript_segments":
        columns.append(UniqueConstraint("chunk_id"))
    if name in ("answer_versions", "chat_replies", "summary_versions"):
        columns.append(Column("version", Integer, nullable=False))
        columns.append(UniqueConstraint(refs[0][0], "version"))
    if name == "jobs":
        columns.extend(
            [
                Column("state", String, nullable=False, index=True),
                Column("slot", String),
                Column("kind", String, nullable=False, index=True),
                Column("lesson_id", String, index=True),
                Column("source_id", String, index=True),
                Column("parent_id", String, index=True),
            ]
        )
    tables[name] = Table(name, metadata, *columns)
Index(
    "uq_active_job_slot",
    tables["jobs"].c.slot,
    unique=True,
    sqlite_where=text("slot IS NOT NULL AND state IN ('queued','running','cancelling')"),
)
question_segments = Table(
    "question_segments",
    metadata,
    Column("question_id", String, ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True),
    Column("segment_id", String, ForeignKey("transcript_segments.id", ondelete="CASCADE"), primary_key=True),
)
events = Table(
    "events",
    metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("created_at", String, nullable=False, index=True),
    Column("data", JSON, nullable=False),
    sqlite_autoincrement=True,
)


class Transaction:
    def __init__(self, conn):
        self.conn = conn

    def get(self, table, identity, required=True):
        row = self.conn.execute(
            select(tables[table].c.data).where(tables[table].c.id == identity)
        ).scalar_one_or_none()
        if row is None and required:
            raise Fault("not_found", "记录不存在", 404)
        return row

    def all(self, table, **where):
        stmt = select(tables[table].c.data)
        for key, value in where.items():
            stmt = stmt.where(tables[table].c[key] == value)
        return list(self.conn.execute(stmt).scalars())

    def active_jobs(self, lesson_id=None):
        table = tables["jobs"]
        stmt = select(table.c.data).where(table.c.state.in_(["queued", "running", "cancelling"]))
        if lesson_id is not None:
            stmt = stmt.where(table.c.lesson_id == lesson_id)
        return list(self.conn.execute(stmt).scalars())

    def save(self, table, obj, new=False):
        obj = dict(obj)
        obj.setdefault("id", uid())
        obj.setdefault("created_at", now())
        obj["updated_at"] = now()
        obj["revision"] = 1 if new else obj.get("revision", 0) + 1
        values = {"id": obj["id"], "data": obj}
        for col in tables[table].columns:
            if col.name not in values:
                key = "attempt" if table == "chat_replies" and col.name == "version" else col.name
                values[col.name] = obj.get(key)
        if new:
            self.conn.execute(tables[table].insert().values(**values))
        else:
            self.conn.execute(tables[table].update().where(tables[table].c.id == obj["id"]).values(**values))
        return obj

    def delete(self, table, identity):
        self.conn.execute(tables[table].delete().where(tables[table].c.id == identity))

    def emit(self, kind, entity, lesson_id=None):
        payload = dict(
            type=kind,
            lesson_id=lesson_id,
            entity_type=kind.split(".")[0],
            entity_id=entity["id"],
            revision=entity.get("revision", 1),
            occurred_at=now(),
            data=entity,
        )
        self.conn.execute(events.insert().values(created_at=now(), data=payload))

    def cursor(self):
        return self.conn.exec_driver_sql("SELECT seq FROM sqlite_sequence WHERE name='events'").scalar() or 0


class Database:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (self.root / "class_copilot.db").exists() or (self.root / ".encryption_key").exists():
            raise RuntimeError("Legacy data directory rejected. Choose an independent directory.")
        self.lock = (self.root / ".lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise RuntimeError("This data directory is already in use") from None
        os.chmod(self.root, 0o700)
        marker = self.root / "schema.json"
        if not marker.exists():
            marker.write_text(json.dumps({"application": "class-copilot-next", "epoch": uid()}))
        info = json.loads(marker.read_text())
        if info.get("application") != "class-copilot-next":
            raise RuntimeError("Incompatible data directory")
        self.epoch = info["epoch"]
        self.engine = create_engine(
            f"sqlite:///{self.root / 'copilot.sqlite3'}", connect_args={"check_same_thread": False}
        )

        @event.listens_for(self.engine, "connect")
        def pragmas(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")

        from alembic import command
        from alembic.config import Config

        cfg = Config()
        cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "migrations"))
        with self.engine.begin() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
        keyfile = self.root / "credential.key"
        if not keyfile.exists():
            fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
        self.crypto = Fernet(keyfile.read_bytes())
        for folder in ("lessons", "uploads", "logs"):
            (self.root / folder).mkdir(exist_ok=True, mode=0o700)
        with self.tx() as tx:
            if not tx.get("settings", "main", False):
                tx.save("settings", dict(id="main", values=Settings().model_dump()), True)
            if not tx.get("credentials", "dashscope", False):
                tx.save("credentials", dict(id="dashscope", secret=None, mask=None, history={}), True)

    @contextmanager
    def tx(self):
        with self.engine.begin() as conn:
            yield Transaction(conn)

    def path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise Fault("storage_unavailable", "无效的存储路径", 503)
        return path

    def secret(self, tx, revision=None):
        c = tx.get("credentials", "dashscope")
        encrypted = (
            c["secret"] if revision is None or revision == c["revision"] else c["history"].get(str(revision))
        )
        if not encrypted:
            raise Fault("provider_not_configured", "请先配置服务地址、区域和 API Key", 503)
        try:
            return self.crypto.decrypt(encrypted.encode()).decode()
        except InvalidToken:
            raise Fault("credential_unreadable", "凭据无法解密，请重新配置 API Key", 503) from None

    def close(self):
        self.engine.dispose()
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()
