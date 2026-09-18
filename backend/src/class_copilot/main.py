from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import audio, dto
from .domain import (
    ACTIVE,
    Analysis,
    AnswerInput,
    AudioTest,
    Automation,
    ChatInput,
    CourseInput,
    CredentialInput,
    DirectAnswer,
    Empty,
    Fault,
    Kind,
    LessonInput,
    LessonPatch,
    ProviderTest,
    Recording,
    ReplyInput,
    Selection,
    Settings,
    SourcePatch,
    SummaryInput,
    merge,
    normalize,
    now,
    uid,
)
from .persistence import Database, events
from .provider import CAPABILITIES, Provider
from .security import RequestSizeLimit
from .service import PUBLIC_TABLES, Service
from .workers import Workers

ROOT = Path(__file__).resolve().parents[3]


def create_app(data_dir=None, provider=None, hardware=None, testing=False):
    @asynccontextmanager
    async def lifespan(app):
        db = Database(Path(data_dir or os.environ.get("CC_NEXT_DATA_DIR", ROOT / "data/next")))
        app.state.db = db
        app.state.service = Service(db)
        app.state.hardware = hardware or audio.AudioHardware()
        app.state.workers = Workers(app.state.service, provider or Provider(), app.state.hardware)
        handler = RotatingFileHandler(db.root / "logs/app.log", maxBytes=2 * 1024 * 1024, backupCount=4)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger = logging.getLogger("class_copilot")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        await app.state.workers.start()
        try:
            yield
        finally:
            await app.state.workers.close()
            logger.removeHandler(handler)
            handler.close()
            db.close()

    app = FastAPI(
        title="Class Copilot",
        version="0.1.0",
        lifespan=lifespan,
        responses={
            code: {"model": dto.ErrorEnvelope}
            for code in (403, 404, 409, 412, 413, 415, 422, 428, 429, 500, 503)
        },
    )
    app.state.csrf = secrets.token_urlsafe(32)

    @app.middleware("http")
    async def boundary(request, call_next):
        request.state.request_id = uid()
        try:
            host = request.url.hostname
            if host not in (
                {"127.0.0.1", "localhost", "::1", "testserver"}
                if testing
                else {"127.0.0.1", "localhost", "::1"}
            ):
                raise Fault("origin_rejected", "只允许本机访问", 403)
            origin = request.headers.get("origin")
            allowed = {f"http://{host}:29038", f"http://{host}:5173", str(request.base_url).rstrip("/")}
            if origin and origin not in allowed:
                raise Fault("origin_rejected", "不允许此访问来源", 403)
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), app.state.csrf):
                    raise Fault("csrf_invalid", "页面令牌已失效，请刷新后再试", 403)
                try:
                    length = int(request.headers.get("content-length", "0"))
                except ValueError:
                    raise Fault("validation_error", "Content-Length 无效", 422) from None
                if length > audio.MAX_BYTES + 1024 * 1024:
                    raise Fault("file_too_large", "上传文件不能超过 500 MiB", 413)
            response = await call_next(request)
        except Fault as exc:
            response = failure(request, exc)
        except Exception:
            logging.getLogger("class_copilot").error(
                "request=%s code=internal_error", request.state.request_id
            )
            response = failure(
                request, Fault("internal_error", "服务出现内部错误，请使用请求编号检查日志", 500)
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    def failure(request, exc):
        error = exc.public()
        error["request_id"] = request.state.request_id
        return JSONResponse({"error": error}, status_code=exc.status)

    @app.exception_handler(Fault)
    async def fault_handler(request, exc):
        return failure(request, exc)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_handler(request, exc):
        return failure(
            request,
            Fault(
                "validation_error",
                "输入格式不符合要求",
                422,
                fields=[{"location": list(e["loc"]), "message": e["msg"]} for e in exc.errors()],
            ),
        )

    @app.exception_handler(IntegrityError)
    async def integrity_handler(request, exc):
        return failure(request, Fault("state_conflict", "该操作与现有记录冲突，请刷新后重试"))

    def ok(request, data, status=200):
        if status == 204:
            return Response(status_code=204)
        return JSONResponse(
            dict(data=data, meta={"request_id": request.state.request_id}), status_code=status
        )

    def s():
        return app.state.service

    def command(request, body, action):
        key = request.headers.get("idempotency-key")
        try:
            key = str(UUID(key or ""))
        except ValueError:
            raise Fault("validation_error", "请提供 UUID 格式的 Idempotency-Key", 422) from None
        with app.state.db.tx() as tx:
            status, data, replayed = s().command(
                tx, key, request.method, request.url.path, body, lambda: action(tx)
            )
        response = ok(request, data, status)
        if replayed:
            response.headers["Idempotent-Replayed"] = "true"
        return response

    def replay_before_preflight(request, body):
        """A completed command remains replayable even if its device disappears."""
        key = request.headers.get("idempotency-key")
        try:
            identity = str(UUID(key or ""))
        except ValueError:
            raise Fault("validation_error", "请提供 UUID 格式的 Idempotency-Key", 422) from None
        with app.state.db.tx() as tx:
            saved = tx.get("idempotency_keys", identity, False)
        if saved and saved["expires_at"] > now():
            return command(request, body, lambda tx: None)
        return None

    def query(request, table, identity):
        with app.state.db.tx() as tx:
            return ok(request, s().public(tx, table, tx.get(table, str(identity))))

    def paged(request, table, filters, cursor, limit):
        with app.state.db.tx() as tx:
            if filters.get("lesson_id"):
                s().lesson(tx, filters["lesson_id"], False)
            if filters.get("source_id"):
                tx.get("audio_sources", filters["source_id"])
            items = tx.all(table, **filters)
            return ok(request, s().page(tx, table, items, cursor, limit, filters))

    @app.get("/api/v1/health", response_model=dto.Envelope[dto.Health])
    async def health(request: Request):
        return ok(request, dict(version="0.1.0", ready=True))

    @app.get("/api/v1/bootstrap", response_model=dto.Envelope[dto.Bootstrap])
    async def bootstrap(request: Request):
        with app.state.db.tx() as tx:
            credential = tx.get("credentials", "dashscope")
            settings = s().settings(tx)["values"]
            return ok(
                request,
                dict(
                    csrf_token=app.state.csrf,
                    configured=bool(
                        credential["secret"]
                        and settings["provider"]["base_url"]
                        and settings["provider"]["region"]
                    ),
                    active_audio=s().audio_slot(tx),
                    capabilities=CAPABILITIES,
                    event_cursor=f"{app.state.db.epoch}:{tx.cursor()}",
                ),
            )

    @app.get("/api/v1/commands/{key}", response_model=dto.Envelope[dto.Command])
    async def get_command(request: Request, key: UUID):
        with app.state.db.tx() as tx:
            saved = tx.get("idempotency_keys", str(key), False)
            if not saved or saved["expires_at"] < now():
                raise Fault("command_unknown", "未找到该命令，过期记录不代表命令从未执行", 404)
            return ok(request, {k: saved[k] for k in ("response_status", "response_body", "expires_at")})

    @app.get("/api/v1/courses", response_model=dto.Envelope[dto.Page[dto.Course]])
    async def courses(request: Request, cursor: str | None = None, limit: int = 50):
        return paged(request, "courses", {}, cursor, limit)

    @app.post("/api/v1/courses", status_code=201, response_model=dto.Envelope[dto.Course])
    async def create_course(request: Request, body: CourseInput):
        def action(tx):
            normalized = normalize(body.name)
            if tx.all("courses", normalized_name=normalized):
                raise Fault("name_conflict", "课程名称已存在")
            course = tx.save("courses", dict(id=uid(), name=body.name, normalized_name=normalized), True)
            s().emit(tx, "courses", course, "course.created")
            return 201, s().public(tx, "courses", course)

        return command(request, body.model_dump(), action)

    @app.patch("/api/v1/courses/{identity}", response_model=dto.Envelope[dto.Course])
    async def patch_course(request: Request, identity: UUID, body: CourseInput):
        with app.state.db.tx() as tx:
            course = tx.get("courses", str(identity))
            s().revision(course, request.headers.get("if-match"))
            normalized = normalize(body.name)
            if any(c["id"] != str(identity) for c in tx.all("courses", normalized_name=normalized)):
                raise Fault("name_conflict", "课程名称已存在")
            course.update(name=body.name, normalized_name=normalized)
            course = tx.save("courses", course)
            s().emit(tx, "courses", course)
            return ok(request, s().public(tx, "courses", course))

    @app.delete("/api/v1/courses/{identity}", status_code=204)
    async def delete_course(request: Request, identity: UUID):
        def action(tx):
            course = tx.get("courses", str(identity))
            if tx.all("lessons", course_id=str(identity)):
                raise Fault("course_not_empty", "课程内仍有课堂，不能删除")
            tx.delete("courses", str(identity))
            tx.emit("course.deleted", dict(id=str(identity), revision=course["revision"] + 1))
            return 204, None

        return command(request, {}, action)

    @app.get("/api/v1/lessons", response_model=dto.Envelope[dto.Page[dto.Lesson]])
    async def lessons(
        request: Request,
        course_id: UUID | None = None,
        q: str = "",
        date_from: date | None = None,
        date_to: date | None = None,
        timezone: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ):
        if len(q) > 200:
            raise Fault("validation_error", "搜索内容不能超过 200 字符", 422)
        start = end = None
        if date_from or date_to:
            try:
                zone = ZoneInfo(timezone or "")
            except (ZoneInfoNotFoundError, ValueError):
                raise Fault("validation_error", "日期筛选需要有效 IANA 时区", 422) from None
            if date_from and date_to and date_from > date_to:
                raise Fault("validation_error", "开始日期不能晚于结束日期", 422)
            start = datetime.combine(date_from, time.min, zone).astimezone(UTC) if date_from else None
            end = (
                datetime.combine(date_to + timedelta(days=1), time.min, zone).astimezone(UTC)
                if date_to
                else None
            )
        with app.state.db.tx() as tx:
            items = tx.all("lessons", **({"course_id": str(course_id)} if course_id else {}))
            items = [
                i
                for i in items
                if (not start or datetime.fromisoformat(i["created_at"]) >= start)
                and (not end or datetime.fromisoformat(i["created_at"]) < end)
            ]
            if q:
                items = [
                    i
                    for i in items
                    if q.casefold()
                    in (
                        s().public(tx, "lessons", i)["display_title"]
                        + tx.get("courses", i["course_id"])["name"]
                    ).casefold()
                ]
            filters = dict(
                course_id=str(course_id),
                q=q,
                date_from=str(date_from),
                date_to=str(date_to),
                timezone=timezone,
            )
            return ok(request, s().page(tx, "lessons", items, cursor, limit, filters, latest=False))

    @app.post("/api/v1/lessons", status_code=201, response_model=dto.Envelope[dto.Lesson])
    async def create_lesson(request: Request, body: LessonInput):
        def action(tx):
            tx.get("courses", body.course_id)
            lesson = tx.save(
                "lessons",
                dict(
                    id=uid(),
                    course_id=body.course_id,
                    custom_title=body.custom_title,
                    lifecycle="ready",
                    automation_mode=body.automation_mode
                    or s().settings(tx)["values"]["automation"]["default_mode"],
                    automation_revision=1,
                    content_revision=0,
                ),
                True,
            )
            s().emit(tx, "lessons", lesson, "lesson.created")
            s().emit(tx, "courses", tx.get("courses", body.course_id))
            return 201, s().public(tx, "lessons", lesson)

        return command(request, body.model_dump(), action)

    @app.get("/api/v1/lessons/{identity}", response_model=dto.Envelope[dto.Lesson])
    async def get_lesson(request: Request, identity: UUID):
        return query(request, "lessons", identity)

    @app.patch("/api/v1/lessons/{identity}", response_model=dto.Envelope[dto.Lesson])
    async def patch_lesson(request: Request, identity: UUID, body: LessonPatch):
        with app.state.db.tx() as tx:
            lesson = s().lesson(tx, str(identity))
            s().revision(lesson, request.headers.get("if-match"))
            lesson.update(body.model_dump(exclude_unset=True))
            lesson = tx.save("lessons", lesson)
            s().emit(tx, "lessons", lesson)
            return ok(request, s().public(tx, "lessons", lesson))

    @app.put("/api/v1/lessons/{identity}/automation", response_model=dto.Envelope[dto.Lesson])
    async def automation(request: Request, identity: UUID, body: Automation):
        with app.state.db.tx() as tx:
            lesson = s().lesson(tx, str(identity))
            s().revision(lesson, request.headers.get("if-match"))
            lesson.update(automation_mode=body.mode, automation_revision=lesson["automation_revision"] + 1)
            lesson = tx.save("lessons", lesson)
            for job in s().active(tx, str(identity)):
                if job["state"] == "queued" and job["snapshot"].get("automatic"):
                    app.state.workers.finish(tx, job, "cancelled")
            s().emit(tx, "lessons", lesson)
            return ok(request, s().public(tx, "lessons", lesson))

    @app.get("/api/v1/lessons/{identity}/snapshot", response_model=dto.Envelope[dto.Snapshot])
    async def snapshot(request: Request, identity: UUID):
        with app.state.db.tx() as tx:
            # Explicit read transaction ensures a coherent cursor and resource snapshot.
            tx.conn.exec_driver_sql("BEGIN")
            lesson = s().lesson(tx, str(identity), False)
            result = dict(
                lesson=s().public(tx, "lessons", lesson),
                active_jobs=[s().public(tx, "jobs", j) for j in s().active(tx, str(identity))],
            )
            for key, table in [
                ("sources", "audio_sources"),
                ("transcripts", "transcript_segments"),
                ("questions", "questions"),
                ("chat_turns", "chat_turns"),
                ("summaries", "summary_versions"),
            ]:
                result[key] = s().page(
                    tx,
                    table,
                    tx.all(table, lesson_id=str(identity)),
                    limit=100,
                    filters={"lesson_id": str(identity)},
                )
            result["event_cursor"] = f"{app.state.db.epoch}:{tx.cursor()}"
            return ok(request, result)

    @app.delete("/api/v1/lessons/{identity}", status_code=202, response_model=dto.Envelope[dto.Accepted])
    async def delete_lesson(request: Request, identity: UUID):
        def action(tx):
            lesson = s().lesson(tx, str(identity))
            if s().active(tx, str(identity)) or any(
                a["capture_state"] in ("preparing", "capturing", "finalizing")
                for a in tx.all("audio_sources", lesson_id=str(identity))
            ):
                raise Fault("lesson_busy", "课堂仍有活动任务，请先停止录音或取消生成")
            lesson["lifecycle"] = "deleting"
            lesson = tx.save("lessons", lesson)
            s().emit(tx, "lessons", lesson, "lesson.deleting")
            job = s().job(tx, "delete_lesson", str(identity))
            return 202, s().accepted(tx, job)

        return command(request, {}, action)

    @app.get("/api/v1/audio/devices", response_model=dto.Envelope[dto.Devices])
    async def devices(request: Request, kind: Kind = "microphone"):
        return ok(request, await asyncio.to_thread(app.state.hardware.devices, kind))

    @app.post("/api/v1/audio/tests", status_code=202, response_model=dto.Envelope[dto.Accepted])
    async def test_audio(request: Request, body: AudioTest):
        if replay := replay_before_preflight(request, body.model_dump()):
            return replay
        await asyncio.to_thread(app.state.hardware.resolve, body.kind, body.device_id)
        return command(
            request,
            body.model_dump(),
            lambda tx: (
                202,
                s().accepted(tx, s().job(tx, "test_audio", snapshot=body.model_dump(), slot="audio")),
            ),
        )

    @app.get("/api/v1/lessons/{identity}/sources", response_model=dto.Envelope[dto.Page[dto.Source]])
    async def sources(request: Request, identity: UUID, cursor: str | None = None, limit: int = 50):
        return paged(request, "audio_sources", {"lesson_id": str(identity)}, cursor, limit)

    @app.post(
        "/api/v1/lessons/{identity}/recordings", status_code=202, response_model=dto.Envelope[dto.Accepted]
    )
    async def recording(request: Request, identity: UUID, body: Recording):
        if replay := replay_before_preflight(request, body.model_dump()):
            return replay
        device = await asyncio.to_thread(app.state.hardware.resolve, body.kind, body.device_id)
        audio.storage_check(app.state.db.root)

        def action(tx):
            s().configured(tx)
            if s().audio_slot(tx):
                raise Fault("audio_busy", "另一项音频处理尚未结束", job_id=s().audio_slot(tx)["id"])
            source = s().new_source(tx, str(identity), body.kind, device_label=device["label"])
            job = s().job(
                tx,
                "start_source",
                str(identity),
                source["id"],
                body.model_dump(),
                dict(type="source", id=source["id"]),
                "audio",
            )
            return 202, s().accepted(tx, job)

        return command(request, body.model_dump(), action)

    @app.get("/api/v1/sources/{identity}", response_model=dto.Envelope[dto.Source])
    async def get_source(request: Request, identity: UUID):
        return query(request, "audio_sources", identity)

    @app.patch("/api/v1/sources/{identity}", response_model=dto.Envelope[dto.Source])
    async def patch_source(request: Request, identity: UUID, body: SourcePatch):
        with app.state.db.tx() as tx:
            source = tx.get("audio_sources", str(identity))
            s().revision(source, request.headers.get("if-match"))
            if source["capture_state"] != "capturing":
                raise Fault("source_not_capturing", "只有采集中的来源可以修改计时")
            source["stop_at"] = (
                (
                    datetime.fromisoformat(source["started_at"])
                    + timedelta(minutes=body.auto_stop_minutes or 240)
                )
                .isoformat()
                .replace("+00:00", "Z")
            )
            source = tx.save("audio_sources", source)
            if source["stop_at"] <= now():
                s().stop(tx, source)
                source = tx.get("audio_sources", str(identity))
            s().emit(tx, "audio_sources", source)
            return ok(request, s().public(tx, "audio_sources", source))

    @app.post(
        "/api/v1/sources/{identity}/stop",
        status_code=202,
        response_model=dto.Envelope[dto.Accepted | dto.SourceStop],
    )
    async def stop(request: Request, identity: UUID, body: Empty):
        return command(request, {}, lambda tx: s().stop(tx, tx.get("audio_sources", str(identity))))

    @app.post("/api/v1/lessons/{identity}/uploads", status_code=201, response_model=dto.Envelope[dto.Source])
    async def upload(request: Request, identity: UUID, file: UploadFile):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in audio.FORMATS:
            raise Fault("unsupported_audio", "请选择 MP3、WAV、M4A、FLAC 或 OGG 文件", 415)
        with app.state.db.tx() as tx:
            s().lesson(tx, str(identity))
        temp = Path(tempfile.mkdtemp(dir=app.state.db.root / "uploads"))
        original, normalized = temp / ("original" + suffix), temp / "normalized.wav"
        try:
            size = 0
            with original.open("wb") as output:
                while block := await file.read(1024 * 1024):
                    size += len(block)
                    if size > audio.MAX_BYTES:
                        raise Fault("file_too_large", "上传文件不能超过 500 MiB", 413)
                    audio.storage_check(temp)
                    await asyncio.to_thread(output.write, block)
            checksum = await asyncio.to_thread(audio.file_hash, original)
            duration = await asyncio.to_thread(audio.validate_audio, original, suffix, normalized)

            def action(tx):
                s().lesson(tx, str(identity))
                for source in tx.all("audio_sources", lesson_id=str(identity)):
                    if any(
                        a["checksum"] == checksum
                        for a in tx.all("audio_assets", source_id=source["id"])
                        if a["role"] == "original"
                    ):
                        raise Fault("duplicate_audio", "该文件已在本课堂中上传", source_id=source["id"])
                source = s().new_source(
                    tx,
                    str(identity),
                    "upload",
                    capture_state="ready",
                    duration_ms=duration,
                    captured_ms=duration,
                    original_filename=Path(file.filename).name[:200],
                )
                target = app.state.db.path(f"lessons/{identity}/{source['id']}")
                target.parent.mkdir(parents=True, exist_ok=True)
                temp.replace(target)
                tx.save(
                    "audio_assets",
                    dict(
                        id=uid(),
                        source_id=source["id"],
                        role="original",
                        relative_path=str((target / original.name).relative_to(app.state.db.root)),
                        checksum=checksum,
                        bytes=size,
                        duration_ms=duration,
                        state="available",
                        mime_type="application/octet-stream",
                    ),
                    True,
                )
                s().emit(tx, "audio_sources", source)
                return 201, s().public(tx, "audio_sources", source)

            return command(request, {"checksum": checksum, "filename": Path(file.filename).name}, action)
        finally:
            await file.close()
            if temp.exists():
                await asyncio.to_thread(shutil.rmtree, temp, True)

    @app.post(
        "/api/v1/sources/{identity}/analysis", status_code=202, response_model=dto.Envelope[dto.Accepted]
    )
    async def analysis(request: Request, identity: UUID, body: Analysis):
        def action(tx):
            source = tx.get("audio_sources", str(identity))
            if source["capture_state"] in ("preparing", "capturing", "finalizing"):
                raise Fault("audio_busy", "请先停止录音并等待本地收尾")
            if source["transcription_state"] == "completed":
                raise Fault("already_processed", "此来源已经全部识别完成")
            snap = app.state.workers.transcription_snapshot(tx, source, body.model_dump())
            job = s().job(tx, "transcribe_source", source["lesson_id"], source["id"], snap, slot="audio")
            source["transcription_state"] = "queued"
            s().emit(tx, "audio_sources", tx.save("audio_sources", source))
            return 202, s().accepted(tx, job)

        return command(request, body.model_dump(), action)

    @app.get("/api/v1/sources/{identity}/segments", response_model=dto.Envelope[dto.SegmentPage])
    async def source_segments(request: Request, identity: UUID, cursor: str | None = None, limit: int = 50):
        with app.state.db.tx() as tx:
            source = tx.get("audio_sources", str(identity))
            page = s().page(
                tx,
                "transcript_segments",
                tx.all("transcript_segments", source_id=str(identity)),
                cursor,
                limit,
                {"source_id": str(identity)},
            )
            page["gaps"] = source["gap_ranges"]
            return ok(request, page)

    @app.get("/api/v1/assets/{identity}/content")
    async def asset(request: Request, identity: UUID, download: bool = False):
        with app.state.db.tx() as tx:
            obj = tx.get("audio_assets", str(identity))
            source = tx.get("audio_sources", obj["source_id"])
            s().lesson(tx, source["lesson_id"])
        path = app.state.db.path(obj["relative_path"])
        if not path.is_file() or obj["state"] not in ("available", "partial"):
            raise Fault("audio_missing", "音频文件缺失或尚未生成", 404)
        filename = (
            source["original_filename"] if obj["role"] == "original" else f"class-{source['ordinal']}.mp3"
        )
        return FileResponse(path, media_type=obj["mime_type"], filename=filename if download else None)

    @app.get("/api/v1/lessons/{identity}/transcripts", response_model=dto.Envelope[dto.Page[dto.Transcript]])
    async def transcripts(
        request: Request,
        identity: UUID,
        source_id: UUID | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ):
        return paged(
            request,
            "transcript_segments",
            dict(lesson_id=str(identity), **({"source_id": str(source_id)} if source_id else {})),
            cursor,
            limit,
        )

    @app.get("/api/v1/lessons/{identity}/questions", response_model=dto.Envelope[dto.Page[dto.Question]])
    async def questions(request: Request, identity: UUID, cursor: str | None = None, limit: int = 50):
        return paged(request, "questions", {"lesson_id": str(identity)}, cursor, limit)

    @app.post(
        "/api/v1/lessons/{identity}/question-detections",
        status_code=202,
        response_model=dto.Envelope[dto.Accepted],
    )
    async def detect(request: Request, identity: UUID, body: Selection):
        return command(
            request,
            body.model_dump(),
            lambda tx: (
                202,
                s().accepted(
                    tx, s().detect(tx, str(identity), s().selected(tx, str(identity), body.segment_ids))
                ),
            ),
        )

    @app.post(
        "/api/v1/lessons/{identity}/direct-answers",
        status_code=202,
        response_model=dto.Envelope[dto.Accepted],
    )
    async def direct(request: Request, identity: UUID, body: DirectAnswer):
        def action(tx):
            s().snapshot_base(tx, str(identity))
            segments = s().selected(tx, str(identity), body.segment_ids)
            question, _ = s().question(
                tx, str(identity), "请解释所选课堂内容并给出参考答案", segments, "direct"
            )
            job, _ = s().generation(
                tx, "generate_answer", str(identity), body.model_dump(), question=question
            )
            return 202, s().accepted(tx, job, dict(type="question", id=question["id"]))

        return command(request, body.model_dump(), action)

    @app.get("/api/v1/questions/{identity}", response_model=dto.Envelope[dto.Question])
    async def get_question(request: Request, identity: UUID):
        return query(request, "questions", identity)

    @app.post(
        "/api/v1/questions/{identity}/answers", status_code=202, response_model=dto.Envelope[dto.Accepted]
    )
    async def answer(request: Request, identity: UUID, body: AnswerInput):
        def action(tx):
            question = tx.get("questions", str(identity))
            job, _ = s().generation(
                tx, "generate_answer", question["lesson_id"], body.model_dump(), question=question
            )
            return 202, s().accepted(tx, job)

        return command(request, body.model_dump(), action)

    @app.get("/api/v1/answers/{identity}", response_model=dto.Envelope[dto.Answer])
    async def get_answer(request: Request, identity: UUID):
        return query(request, "answer_versions", identity)

    @app.get("/api/v1/lessons/{identity}/chat-turns", response_model=dto.Envelope[dto.Page[dto.ChatTurn]])
    async def turns(request: Request, identity: UUID, cursor: str | None = None, limit: int = 50):
        return paged(request, "chat_turns", {"lesson_id": str(identity)}, cursor, limit)

    @app.post(
        "/api/v1/lessons/{identity}/chat-turns", status_code=202, response_model=dto.Envelope[dto.Accepted]
    )
    async def chat(request: Request, identity: UUID, body: ChatInput):
        def action(tx):
            s().snapshot_base(tx, str(identity))
            ordinal = (
                max((t["ordinal"] for t in tx.all("chat_turns", lesson_id=str(identity))), default=0) + 1
            )
            turn = tx.save(
                "chat_turns",
                dict(
                    id=uid(),
                    lesson_id=str(identity),
                    ordinal=ordinal,
                    user_content=body.content,
                    options=body.model_dump(exclude={"content"}),
                ),
                True,
            )
            job, _ = s().generation(tx, "chat_reply", str(identity), body.model_dump(), turn=turn)
            s().bump(tx, str(identity))
            s().emit(tx, "chat_turns", turn, "chat_turn.created")
            return 202, s().accepted(tx, job, dict(type="chat_turn", id=turn["id"]))

        return command(request, body.model_dump(), action)

    @app.get("/api/v1/chat-turns/{identity}", response_model=dto.Envelope[dto.ChatTurn])
    async def get_turn(request: Request, identity: UUID):
        return query(request, "chat_turns", identity)

    @app.post(
        "/api/v1/chat-turns/{identity}/replies", status_code=202, response_model=dto.Envelope[dto.Accepted]
    )
    async def reply(request: Request, identity: UUID, body: ReplyInput):
        def action(tx):
            turn = tx.get("chat_turns", str(identity))
            job, _ = s().generation(tx, "chat_reply", turn["lesson_id"], body.model_dump(), turn=turn)
            return 202, s().accepted(tx, job)

        return command(request, body.model_dump(), action)

    @app.get("/api/v1/lessons/{identity}/summaries", response_model=dto.Envelope[dto.Page[dto.Summary]])
    async def summaries(request: Request, identity: UUID, cursor: str | None = None, limit: int = 50):
        return paged(request, "summary_versions", {"lesson_id": str(identity)}, cursor, limit)

    @app.post(
        "/api/v1/lessons/{identity}/summaries", status_code=202, response_model=dto.Envelope[dto.Accepted]
    )
    async def summary(request: Request, identity: UUID, body: SummaryInput):
        def action(tx):
            job, _ = s().generation(tx, "summarize_lesson", str(identity), body.model_dump())
            return 202, s().accepted(tx, job)

        return command(request, body.model_dump(), action)

    @app.get("/api/v1/summaries/{identity}", response_model=dto.Envelope[dto.Summary])
    async def get_summary(request: Request, identity: UUID):
        return query(request, "summary_versions", identity)

    @app.get("/api/v1/settings", response_model=dto.Envelope[dto.PublicSettings])
    async def settings(request: Request):
        return query(request, "settings", "main")

    @app.patch("/api/v1/settings", response_model=dto.Envelope[dto.PublicSettings])
    async def patch_settings(request: Request, body: dict):
        with app.state.db.tx() as tx:
            obj = s().settings(tx)
            s().revision(obj, request.headers.get("if-match"))
            obj["values"] = Settings.model_validate(merge(obj["values"], body)).model_dump()
            obj = tx.save("settings", obj)
            tx.emit("settings.updated", s().public(tx, "settings", obj))
            return ok(request, s().public(tx, "settings", obj))

    @app.get("/api/v1/providers/dashscope/credential", response_model=dto.Envelope[dto.Credential])
    async def credential(request: Request):
        return query(request, "credentials", "dashscope")

    @app.put("/api/v1/providers/dashscope/credential", response_model=dto.Envelope[dto.Credential])
    async def put_credential(request: Request, body: CredentialInput):
        with app.state.db.tx() as tx:
            obj = tx.get("credentials", "dashscope")
            s().revision(obj, request.headers.get("if-match"))
            if obj["secret"]:
                obj["history"][str(obj["revision"])] = obj["secret"]
            obj.update(
                secret=app.state.db.crypto.encrypt(body.api_key.encode()).decode(),
                mask="••••" + (body.api_key[-4:] if len(body.api_key) > 8 else ""),
            )
            obj = tx.save("credentials", obj)
            public = s().public(tx, "credentials", obj)
            tx.emit("credential.updated", public)
            return ok(request, public)

    @app.delete("/api/v1/providers/dashscope/credential", status_code=204)
    async def delete_credential(request: Request):
        def action(tx):
            if any(j["kind"] not in ("delete_lesson", "test_audio") for j in s().active(tx)):
                raise Fault("job_busy", "仍有任务使用凭据，请先停止或取消")
            obj = tx.get("credentials", "dashscope")
            obj.update(secret=None, mask=None, history={})
            obj = tx.save("credentials", obj)
            tx.emit("credential.updated", s().public(tx, "credentials", obj))
            return 204, None

        return command(request, {}, action)

    @app.post("/api/v1/providers/dashscope/tests", status_code=202, response_model=dto.Envelope[dto.Accepted])
    async def test_provider(request: Request, body: ProviderTest):
        def action(tx):
            config = s().configured(tx)
            model = config["values"]["models"][
                "transcription"
                if body.capability == "transcription"
                else "chat_" + (body.model_role or "fast")
            ]
            snapshot = dict(
                settings=config["values"],
                settings_revision=config["revision"],
                credential_revision=tx.get("credentials", "dashscope")["revision"],
                model=model,
                capability=body.capability,
                messages=[
                    {
                        "role": "user",
                        "content": "Return OK. For audio, transcribe speech only; silence means empty text.",
                    }
                ],
            )
            job = s().job(tx, "test_provider", snapshot=snapshot)
            return 202, s().accepted(tx, job)

        return command(request, body.model_dump(), action)

    @app.get("/api/v1/jobs", response_model=dto.Envelope[dto.Page[dto.Job]])
    async def jobs(
        request: Request,
        lesson_id: UUID | None = None,
        state: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ):
        with app.state.db.tx() as tx:
            items = tx.all(
                "jobs",
                **({"lesson_id": str(lesson_id)} if lesson_id else {}),
                **({"state": state} if state else {}),
            )
            return ok(
                request,
                s().page(tx, "jobs", items, cursor, limit, dict(lesson_id=str(lesson_id), state=state)),
            )

    @app.get("/api/v1/jobs/{identity}", response_model=dto.Envelope[dto.Job])
    async def get_job(request: Request, identity: UUID):
        return query(request, "jobs", identity)

    @app.post("/api/v1/jobs/{identity}/cancel", status_code=202, response_model=dto.Envelope[dto.Job])
    async def cancel(request: Request, identity: UUID, body: Empty):
        def action(tx):
            job = tx.get("jobs", str(identity))
            if job["state"] not in ACTIVE:
                return 200, s().public(tx, "jobs", job)
            if job["kind"] in ("start_source", "finalize_source", "delete_lesson"):
                raise Fault("job_not_cancellable", "此任务不能取消；录音请使用停止按钮")
            if job["kind"] == "transcribe_source" and tx.get("audio_sources", job["source_id"])[
                "capture_state"
            ] in ("capturing", "preparing"):
                raise Fault("job_not_cancellable", "请先停止实时录音")
            job["cancel_requested"] = True
            if job["state"] == "queued":
                job = app.state.workers.finish(tx, job, "cancelled")
                return 200, s().public(tx, "jobs", job)
            job["state"] = "cancelling"
            job = tx.save("jobs", job)
            s().emit(tx, "jobs", job)
            return 202, s().public(tx, "jobs", job)

        return command(request, {}, action)

    @app.post("/api/v1/jobs/{identity}/retry", status_code=202, response_model=dto.Envelope[dto.Accepted])
    async def retry(request: Request, identity: UUID, body: Empty):
        def action(tx):
            old = tx.get("jobs", str(identity))
            if old["state"] not in ("failed", "cancelled", "interrupted") or old["kind"] == "start_source":
                raise Fault("job_not_retryable", "此任务不能重试")
            snap = old["snapshot"]
            snap.pop("summary_scheduled", None)
            if "settings" in snap:
                s().configured(tx)
                snap["credential_revision"] = tx.get("credentials", "dashscope")["revision"]
            if old["kind"] in ("generate_answer", "chat_reply", "summarize_lesson"):
                entity = tx.get(PUBLIC_TABLES[old["resource"]["type"]], old["resource"]["id"])
                question = (
                    tx.get("questions", entity["question_id"]) if old["kind"] == "generate_answer" else None
                )
                turn = tx.get("chat_turns", entity["turn_id"]) if old["kind"] == "chat_reply" else None
                job, _ = s().generation(
                    tx, old["kind"], old["lesson_id"], snap.get("options"), question, turn, snap, old["id"]
                )
            else:
                if old["kind"] == "transcribe_source":
                    source = tx.get("audio_sources", old["source_id"])
                    if source["capture_state"] in ("capturing", "preparing", "finalizing"):
                        raise Fault("audio_busy", "请先停止录音并等待收尾")
                job = s().job(
                    tx,
                    old["kind"],
                    old.get("lesson_id"),
                    old.get("source_id"),
                    snap,
                    slot="audio" if old["kind"] in ("transcribe_source", "test_audio") else None,
                    retry_of=old["id"],
                )
            return 202, s().accepted(tx, job)

        return command(request, {}, action)

    @app.get("/api/v1/lessons/{identity}/export")
    async def export(request: Request, identity: UUID, format: str = "markdown"):
        if format != "markdown":
            raise Fault("validation_error", "只支持 Markdown 导出", 422)
        with app.state.db.tx() as tx:
            tx.conn.exec_driver_sql("BEGIN")
            lesson = s().public(tx, "lessons", s().lesson(tx, str(identity)))
            lines = [
                f"# {lesson['display_title']}",
                "",
                f"课程：{lesson['course_name']}",
                f"创建时间（UTC）：{lesson['created_at']}",
                "",
                "## 音频来源",
            ]
            for source in tx.all("audio_sources", lesson_id=str(identity)):
                lines.extend(
                    [
                        f"- 来源 {source['ordinal']} · {source['kind']} · {source['duration_ms']} ms · {source['capture_state']} / {source['transcription_state']}",
                        f"  未识别区间：{json.dumps(source['gap_ranges'], ensure_ascii=False)}",
                    ]
                )
                for asset in tx.all("audio_assets", source_id=source["id"]):
                    lines.append(f"  - {asset['role']} · {asset['state']} · {asset['bytes']} bytes")
            lines.extend(["", "## 最终转写"])
            for seg in s().material(tx, str(identity))[0]:
                lines.extend(
                    [
                        f"### 来源 {seg['source_ordinal']} · {seg['start_ms']}–{seg['end_ms']} ms",
                        seg["text"],
                        "",
                    ]
                )
            lines.append("## 课堂问答（AI 参考）")
            for q in tx.all("questions", lesson_id=str(identity)):
                lines.extend(
                    [f"### {q['text']}", f"来源：{q['origin']} · 片段：{', '.join(q['segment_ids'])}"]
                )
                versions = tx.all("answer_versions", question_id=q["id"])
                if not versions:
                    lines.append("待回答")
                for a in versions:
                    lines.extend(
                        [
                            f"#### 版本 {a['version']} · {a['style']} · {a['language']} · {a['model']} · {a['state']}",
                            a["content"] or "（尚无内容）",
                            "",
                        ]
                    )
            lines.append("## 课堂聊天")
            for t in tx.all("chat_turns", lesson_id=str(identity)):
                lines.extend([f"### 用户 · {t['created_at']}", t["user_content"], ""])
                replies = tx.all("chat_replies", turn_id=t["id"])
                if not replies:
                    lines.append("（尚未回复）")
                for r in replies:
                    lines.extend(
                        [
                            f"#### 回复尝试 {r['attempt']} · {r['model']} · {r['state']}",
                            r["content"] or "（尚无内容）",
                            "",
                        ]
                    )
            lines.append("## 总结版本")
            for summary in tx.all("summary_versions", lesson_id=str(identity)):
                lines.extend(
                    [
                        f"### 版本 {summary['version']} · {summary['state']} · {summary['model']}",
                        f"覆盖：{json.dumps(summary['context_coverage'], ensure_ascii=False)}",
                        summary["content"] or "（尚无内容）",
                        "",
                    ]
                )
        return Response(
            "\n".join(lines),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="class-{identity}.md"'},
        )

    @app.get("/api/v1/events")
    async def stream_events(request: Request, after: str | None = None):
        db = app.state.db
        cursor = request.headers.get("last-event-id") or after
        with db.tx() as tx:
            water = tx.cursor()
            floor = tx.conn.execute(select(events.c.seq).order_by(events.c.seq).limit(1)).scalar() or water
        invalid = None
        try:
            epoch, number = cursor.split(":") if cursor else (db.epoch, str(water))
            seq = int(number)
            if epoch != db.epoch or seq > water or seq < max(0, floor - 1):
                invalid = "cursor_expired"
        except (ValueError, AttributeError):
            seq, invalid = water, "invalid_cursor"

        async def generate():
            nonlocal seq
            if invalid:
                yield "event: reset_required\ndata: " + json.dumps({"reason": invalid}) + "\n\n"
                return
            heartbeat, live_seen = time_module(), {}
            while not await request.is_disconnected():
                with db.tx() as tx:
                    minimum = (
                        tx.conn.execute(select(events.c.seq).order_by(events.c.seq).limit(1)).scalar()
                        or tx.cursor()
                    )
                    expired = seq < max(0, minimum - 1)
                    rows = tx.conn.execute(
                        select(events.c.seq, events.c.data)
                        .where(events.c.seq > seq)
                        .order_by(events.c.seq)
                        .limit(200)
                    ).all()
                if expired:
                    yield 'event: reset_required\ndata: {"reason":"slow_consumer"}\n\n'
                    return
                for number, payload in rows:
                    seq = number
                    event_cursor = f"{db.epoch}:{seq}"
                    payload["cursor"] = event_cursor
                    event_name = (
                        "entity.deleted" if payload["type"].endswith(".deleted") else "entity.updated"
                    )
                    yield f"id: {event_cursor}\nevent: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                for key, payload in list(app.state.workers.live.items()):
                    if live_seen.get(key, 0) < payload["revision"]:
                        live_seen[key] = payload["revision"]
                        yield "event: live\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
                if time_module() - heartbeat > 15:
                    yield ": heartbeat\n\n"
                    heartbeat = time_module()
                await asyncio.sleep(0.2)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/{path:path}", include_in_schema=False)
    async def web(path: str):
        if path.startswith("api/"):
            raise Fault("not_found", "接口不存在", 404)
        root = ROOT / "web/dist"
        target = (root / path).resolve()
        if target.is_relative_to(root) and target.is_file():
            return FileResponse(target)
        if (root / "index.html").is_file():
            return FileResponse(root / "index.html")
        return Response("Frontend not built. Run: cd web && npm ci && npm run build", status_code=503)

    app.add_middleware(RequestSizeLimit)

    def openapi_contract():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        for path, methods in schema["paths"].items():
            for method, operation in methods.items():
                if method not in ("get", "post", "put", "patch", "delete"):
                    continue
                parameters = operation.setdefault("parameters", [])
                if method in ("post", "put", "patch", "delete"):
                    parameters.append(
                        dict(
                            name="X-CSRF-Token", **{"in": "header"}, required=True, schema={"type": "string"}
                        )
                    )
                if method in ("post", "delete"):
                    parameters.append(
                        dict(
                            name="Idempotency-Key",
                            **{"in": "header"},
                            required=True,
                            schema={"type": "string", "format": "uuid"},
                        )
                    )
                if method in ("put", "patch"):
                    parameters.append(
                        dict(
                            name="If-Match",
                            **{"in": "header"},
                            required=True,
                            schema={"type": "string"},
                            description='Quoted resource revision, e.g. "3"',
                        )
                    )
                for response in operation.get("responses", {}).values():
                    response.setdefault("headers", {})["X-Request-ID"] = {"schema": {"type": "string"}}
                if path.endswith("/events") and method == "get":
                    operation["responses"]["200"]["content"] = {
                        "text/event-stream": {"schema": {"type": "string"}}
                    }
                elif path.endswith("/content") and method == "get":
                    operation["responses"]["200"]["content"] = {
                        "audio/mpeg": {"schema": {"type": "string", "format": "binary"}}
                    }
                elif path.endswith("/export") and method == "get":
                    operation["responses"]["200"]["content"] = {
                        "text/markdown": {"schema": {"type": "string"}}
                    }
        app.openapi_schema = schema
        return schema

    app.openapi = openapi_contract
    return app


def time_module():
    import time as clock

    return clock.monotonic()


app = create_app()
