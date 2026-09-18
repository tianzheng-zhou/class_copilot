from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import shutil
import time
import wave
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher

import numpy as np
from pydantic import ValidationError

from . import audio, context
from .domain import ACTIVE, DetectionResult, Fault, normalize, now, uid
from .persistence import events
from .service import PUBLIC_TABLES

log = logging.getLogger("class_copilot.jobs")
LOCAL = ("delete_lesson", "finalize_source")


class Workers:
    def __init__(self, service, provider, hardware):
        self.s = service
        self.db, self.provider, self.hardware = service.db, provider, hardware
        self.tasks, self.captures, self.buffers = {}, {}, {}
        self.live = {}
        self.closing = False
        self.loop_task = None

    async def local_work(self, function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    def publish(self, kind, **data):
        key = kind + ":" + str(data.get("source_id") or data.get("job_id"))
        self.live[key] = dict(type=kind, cursor=None, revision=time.monotonic_ns(), **data)
        if len(self.live) > 100:
            self.live.pop(next(iter(self.live)))

    async def start(self):
        await self.recover()
        self.loop_task = asyncio.create_task(self.schedule())

    async def recover(self):
        repairs = []
        with self.db.tx() as tx:
            for job in self.s.active(tx):
                if job["kind"] in LOCAL:
                    job.update(state="queued", cancel_requested=False)
                    self.s.emit(tx, "jobs", tx.save("jobs", job))
                else:
                    self.finish(
                        tx,
                        job,
                        "interrupted",
                        Fault("process_interrupted", "应用曾中断，请显式重试", 503, True),
                    )
            for original in tx.all("jobs", kind="transcribe_source"):
                if original["snapshot"].get("generate_summary") and not original["snapshot"].get(
                    "summary_scheduled"
                ):
                    original["snapshot"]["summary_scheduled"] = True
                    original["progress"]["summary_deferred"] = "restart_requires_confirmation"
                    tx.save("jobs", original)
            for source in tx.all("audio_sources"):
                if source["capture_state"] in ("preparing", "capturing", "finalizing"):
                    source.update(
                        capture_state="interrupted",
                        stopped_at=now(),
                        transcription_state="partial",
                        error=Fault(
                            "process_interrupted", "录音曾中断，已保存音频块将被恢复", 503, True
                        ).public(),
                    )
                    directory = self.db.path(f"lessons/{source['lesson_id']}/{source['id']}/chunks")
                    if directory.exists():
                        existing = {c["ordinal"] for c in tx.all("audio_chunks", source_id=source["id"])}
                        for partial in directory.glob("*.wav.part"):
                            try:
                                with wave.open(str(partial)) as f:
                                    f.readframes(f.getnframes())
                                partial.replace(partial.with_suffix(""))
                            except (OSError, wave.Error, EOFError):
                                pass
                        for path in sorted(directory.glob("*.wav")):
                            try:
                                ordinal = int(path.stem)
                                with wave.open(str(path)) as f:
                                    duration = f.getnframes() * 1000 // f.getframerate()
                                if ordinal not in existing:
                                    manifest = path.with_suffix(".wav.json")
                                    record = (
                                        json.loads(manifest.read_text())
                                        if manifest.exists()
                                        else dict(
                                            ordinal=ordinal,
                                            start_ms=source["captured_ms"],
                                            end_ms=source["captured_ms"] + duration,
                                            checksum=audio.file_hash(path),
                                        )
                                    )
                                    self.register_chunk(tx, source, record, path)
                                    source["captured_ms"] = max(source["captured_ms"], record["end_ms"])
                            except (ValueError, OSError, wave.Error):
                                source["gap_ranges"].append(
                                    dict(
                                        start_ms=source["captured_ms"],
                                        end_ms=source["captured_ms"],
                                        reason="unreadable_chunk",
                                    )
                                )
                    source["gap_ranges"].append(
                        dict(
                            start_ms=source["captured_ms"],
                            end_ms=source["captured_ms"]
                            + source["settings_snapshot"]["transcription"]["max_chunk_seconds"] * 1000,
                            reason="possible_unflushed_audio",
                        )
                    )
                    source["duration_ms"] = source["captured_ms"]
                    source = tx.save("audio_sources", source)
                    self.s.emit(tx, "audio_sources", source)
                    if not any(
                        j["kind"] == "finalize_source" and j.get("source_id") == source["id"]
                        for j in self.s.active(tx)
                    ):
                        repairs.append(source)
            for source in repairs:
                self.s.job(tx, "finalize_source", source["lesson_id"], source["id"])
        # Only this version's temporary upload area is cleaned.
        for path in self.db.path("uploads").iterdir():
            if path.is_dir():
                await asyncio.to_thread(shutil.rmtree, path, True)

    async def schedule(self):
        iteration = 0
        while not self.closing:
            with self.db.tx() as tx:
                queued = [j for j in tx.all("jobs", state="queued")]
                # Reserve one text lane for chat; oldest tasks get the other lane.
                queued.sort(key=lambda j: (j["kind"] != "chat_reply", j["created_at"]))
                running = [tx.get("jobs", identity) for identity in self.tasks]
                for job in queued:
                    text_kind = job["kind"] in (
                        "detect_questions",
                        "generate_answer",
                        "chat_reply",
                        "summarize_lesson",
                        "test_provider",
                    )
                    text_running = [
                        j
                        for j in running
                        if j["kind"]
                        in (
                            "detect_questions",
                            "generate_answer",
                            "chat_reply",
                            "summarize_lesson",
                            "test_provider",
                        )
                    ]
                    if text_kind and (
                        len(text_running) >= 2
                        or (
                            job["kind"] != "chat_reply"
                            and any(j["kind"] != "chat_reply" for j in text_running)
                        )
                    ):
                        continue
                    if (
                        not text_kind
                        and len(
                            [
                                j
                                for j in running
                                if j["kind"]
                                not in (
                                    "chat_reply",
                                    "generate_answer",
                                    "detect_questions",
                                    "summarize_lesson",
                                )
                            ]
                        )
                        >= 4
                    ):
                        continue
                    job.update(state="running", started_at=now())
                    job = tx.save("jobs", job)
                    self.s.emit(tx, "jobs", job)
                    self.tasks[job["id"]] = asyncio.create_task(self.execute(job))
                    running.append(job)
                for job in self.s.active(tx):
                    if (
                        job["cancel_requested"]
                        and job["id"] in self.tasks
                        and not self.tasks[job["id"]].cancelling()
                    ):
                        self.tasks[job["id"]].cancel()
                for original in tx.all("jobs", kind="transcribe_source"):
                    if original["kind"] != "transcribe_source" or original["state"] not in (
                        "succeeded",
                        "failed",
                    ):
                        continue
                    snap = original["snapshot"]
                    if not snap.get("generate_summary") or snap.get("summary_scheduled"):
                        continue
                    source = tx.get("audio_sources", original["source_id"], False)
                    if not source or source["capture_state"] in ("capturing", "preparing", "finalizing"):
                        continue
                    if any(
                        j.get("parent_id") == original["id"]
                        or j.get("slot") == "summary:" + original["lesson_id"]
                        for j in self.s.active(tx)
                    ):
                        continue
                    snap["summary_scheduled"] = True
                    tx.save("jobs", original)
                    if tx.all("transcript_segments", lesson_id=original["lesson_id"]):
                        try:
                            self.s.generation(
                                tx,
                                "summarize_lesson",
                                original["lesson_id"],
                                options={"include_chat": snap.get("include_chat_in_summary", False)},
                            )
                        except Fault as error:
                            original["progress"]["summary_error"] = error.public()
                            tx.save("jobs", original)
                iteration += 1
                if iteration % 600 == 0:
                    cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat().replace("+00:00", "Z")
                    water = tx.cursor()
                    tx.conn.execute(
                        events.delete().where(
                            (events.c.created_at < cutoff) | (events.c.seq <= water - 100000)
                        )
                    )
            await asyncio.sleep(0.1)

    def checkpoint(self, tx, job, content, state="streaming", error=None):
        resource = job.get("resource")
        if not resource or resource["type"] not in ("answer_version", "chat_reply", "summary_version"):
            return
        table = PUBLIC_TABLES[resource["type"]]
        entity = tx.get(table, resource["id"], False)
        if not entity:
            return
        entity.update(content=content, state=state, error=error.public() if error else None)
        if state != "streaming":
            entity["finished_at"] = now()
        entity = tx.save(table, entity)
        self.s.emit(tx, table, entity)
        if table == "chat_replies":
            turn = tx.get("chat_turns", entity["turn_id"])
            turn = tx.save("chat_turns", turn)
            self.s.emit(tx, "chat_turns", turn)
        if state == "completed" and table != "summary_versions":
            self.s.bump(tx, job["lesson_id"])
        if table == "answer_versions":
            self.s.emit(tx, "questions", tx.get("questions", entity["question_id"]))

    def finish(self, tx, job, state, error=None):
        job.update(state=state, finished_at=now(), error=error.public() if error else None)
        job = tx.save("jobs", job)
        self.s.emit(tx, "jobs", job)
        result_state = {
            "succeeded": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
            "interrupted": "interrupted",
        }[state]
        resource = job.get("resource")
        content = self.buffers.get(job["id"])
        if (
            content is None
            and resource
            and resource["type"] in ("answer_version", "chat_reply", "summary_version")
        ):
            entity = tx.get(PUBLIC_TABLES[resource["type"]], resource["id"], False)
            content = entity["content"] if entity else ""
        self.checkpoint(tx, job, content or "", result_state, error)
        if job["kind"] == "transcribe_source" and state != "succeeded":
            source = tx.get("audio_sources", job["source_id"])
            chunks = tx.all("audio_chunks", source_id=source["id"])
            source["transcription_state"] = (
                "cancelled"
                if state == "cancelled"
                else "partial"
                if any(c["state"] == "completed" for c in chunks)
                else "failed"
            )
            source["gap_ranges"] = [
                g
                for g in source["gap_ranges"]
                if g["reason"]
                in (
                    "possible_unflushed_audio",
                    "capture_overflow",
                    "storage_unavailable",
                    "audio_disconnected",
                )
            ] + [
                dict(
                    start_ms=c["start_ms"],
                    end_ms=c["end_ms"],
                    reason=(c.get("error") or {}).get("code", "unprocessed"),
                )
                for c in chunks
                if c["state"] != "completed"
            ]
            source["error"] = error.public() if error else None
            # Recording continues after provider failure, so preserve audio exclusivity until capture stops.
            if source["capture_state"] in ("capturing", "finalizing", "preparing"):
                holders = [j for j in self.s.active(tx) if j.get("slot") == "audio"]
                if not holders:
                    holder = self.s.job(
                        tx,
                        "finalize_source",
                        source["lesson_id"],
                        source["id"],
                        snapshot={"wait_for_stop": True},
                        slot="audio",
                    )
                    holder["progress"]["phase"] = "recording_without_transcription"
                    tx.save("jobs", holder)
            source = tx.save("audio_sources", source)
            self.s.emit(tx, "audio_sources", source)
        return job

    async def execute(self, job):
        try:
            await getattr(self, "run_" + job["kind"])(job)
            with self.db.tx() as tx:
                current = tx.get("jobs", job["id"])
                if current["state"] in ACTIVE:
                    self.finish(tx, current, "cancelled" if current["cancel_requested"] else "succeeded")
        except asyncio.CancelledError:
            with self.db.tx() as tx:
                self.finish(tx, tx.get("jobs", job["id"]), "interrupted" if self.closing else "cancelled")
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, Fault)
                else Fault("internal_error", "任务失败，请检查运行环境后重试", 500, True)
            )
            log.error(
                "job=%s lesson=%s kind=%s code=%s", job["id"], job.get("lesson_id"), job["kind"], error.code
            )
            with self.db.tx() as tx:
                current = tx.get("jobs", job["id"])
                self.finish(tx, current, "failed", error)
                if job["kind"] == "start_source":
                    source = tx.get("audio_sources", job["source_id"])
                    source.update(capture_state="failed", error=error.public())
                    self.s.emit(tx, "audio_sources", tx.save("audio_sources", source))
                elif job["kind"] == "finalize_source":
                    source = tx.get("audio_sources", job["source_id"])
                    if source["capture_state"] == "finalizing":
                        source["capture_state"] = "ready"
                    source["error"] = error.public()
                    self.s.emit(tx, "audio_sources", tx.save("audio_sources", source))
        finally:
            self.tasks.pop(job["id"], None)
            self.buffers.pop(job["id"], None)

    async def stream(self, job, messages=None, audio_bytes=None, structured=False, checkpoint=True):
        snap = job["snapshot"]
        with self.db.tx() as tx:
            secret = self.db.secret(tx, snap.get("credential_revision"))
        messages = messages or snap["messages"]
        budget = 8000 if job["kind"] == "detect_questions" else 32000
        if sum(context.cost(m["content"]) for m in messages) > budget:
            raise Fault("context_too_large", "模型请求超过统一输入预算", 422)
        content, saved, stamp = "", 0, time.monotonic()

        async def checkpoint_clock():
            previous = ""
            while True:
                await asyncio.sleep(0.8)
                current_content = self.buffers.get(job["id"], "")
                if current_content and current_content != previous:
                    with self.db.tx() as tx:
                        self.checkpoint(tx, job, current_content)
                    previous = current_content

        timer = asyncio.create_task(checkpoint_clock()) if checkpoint else None
        try:
            async for item in self.provider.stream(
                snap["settings"],
                secret,
                snap["model"],
                messages or snap["messages"],
                thinking=snap.get("thinking", False),
                audio=audio_bytes,
                structured=structured,
            ):
                if item.get("text"):
                    content += item["text"]
                    if checkpoint:
                        self.buffers[job["id"]] = content
                        self.publish(
                            "generation.draft",
                            job_id=job["id"],
                            lesson_id=job.get("lesson_id"),
                            content=content,
                        )
                        if len(content.encode()) - saved >= 1024 or time.monotonic() - stamp >= 1:
                            with self.db.tx() as tx:
                                self.checkpoint(tx, job, content)
                            saved, stamp = len(content.encode()), time.monotonic()
                    elif audio_bytes:
                        self.publish(
                            "transcription.draft",
                            job_id=job["id"],
                            source_id=job.get("source_id"),
                            lesson_id=job.get("lesson_id"),
                            content=content,
                        )
                if item.get("usage") or item.get("actual_model"):
                    with self.db.tx() as tx:
                        current = tx.get("jobs", job["id"])
                        current["usage"] = item.get("usage") or current.get("usage")
                        current["actual_model"] = item.get("actual_model") or current.get("actual_model")
                        tx.save("jobs", current)
            return content
        finally:
            if checkpoint:
                self.buffers[job["id"]] = content
            if timer:
                timer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await timer

    async def run_generate_answer(self, job):
        await self.stream(job)

    run_chat_reply = run_generate_answer

    async def run_detect_questions(self, job):
        raw = await self.stream(job, structured=True, checkpoint=False)
        try:
            result = DetectionResult.model_validate_json(raw)
        except ValidationError:
            raise Fault("invalid_detection", "问题检测结果格式无效，请重试", 503) from None
        with self.db.tx() as tx:
            snapshot = job["snapshot"]
            lesson = self.s.lesson(tx, job["lesson_id"])
            segments = self.s.selected(tx, job["lesson_id"], snapshot["segment_ids"])
            settings = snapshot["settings"]["detection"]
            duplicates = []
            for item in result.questions:
                if item.confidence < settings["confidence_threshold"]:
                    continue
                previous = tx.all("questions", lesson_id=lesson["id"])
                current = datetime.now(UTC)
                if snapshot["automatic"] and previous:
                    last = max(datetime.fromisoformat(q["created_at"]) for q in previous)
                    if (current - last).total_seconds() < settings["cooldown_seconds"]:
                        continue
                duplicate = next(
                    (
                        q
                        for q in previous
                        if settings["dedup_window_seconds"]
                        and (current - datetime.fromisoformat(q["created_at"])).total_seconds()
                        < settings["dedup_window_seconds"]
                        and SequenceMatcher(None, normalize(q["text"]), normalize(item.text)).ratio() >= 0.85
                    ),
                    None,
                )
                if duplicate:
                    duplicates.append(duplicate["id"])
                    continue
                question, created = self.s.question(
                    tx,
                    lesson["id"],
                    item.text,
                    segments,
                    "auto" if snapshot["automatic"] else "manual_detection",
                    item.confidence,
                )
                if (
                    created
                    and snapshot["automatic"]
                    and lesson["automation_mode"] == "auto_answer"
                    and lesson["automation_revision"] == snapshot["automation_revision"]
                ):
                    answer_job, _ = self.s.generation(tx, "generate_answer", lesson["id"], question=question)
                    answer_job["snapshot"]["automatic"] = True
                    answer_job["parent_id"] = job["parent_id"] or job["id"]
                    tx.save("jobs", answer_job)
            current_job = tx.get("jobs", job["id"])
            current_job["progress"] = dict(
                phase="completed",
                completed=len(result.questions),
                total=len(result.questions),
                unit="questions",
                duplicate_ids=duplicates,
            )
            tx.save("jobs", current_job)

    async def run_summarize_lesson(self, job):
        snap = job["snapshot"]
        material = list(snap["summary_material"])
        auxiliary = snap["summary_auxiliary"]
        extras = [(q["id"], "Classroom question: " + q["text"]) for q in auxiliary["questions"]]
        extras += [(a["id"], "AI reference answer: " + a["content"]) for a in auxiliary["answers"]]
        for turn in auxiliary["turns"]:
            extras.append((turn["id"], "User chat: " + turn["user_content"]))
            successful = [r for r in turn["replies"] if r["state"] == "completed"]
            if successful:
                extras.append((successful[-1]["id"], "Assistant reply: " + successful[-1]["content"]))
        for index, (identity, text) in enumerate(extras):
            material.append(
                dict(id=identity, source_id="auxiliary", ordinal=index, start_ms=0, end_ms=0, text=text)
            )
        # Hierarchical map/reduce with bounded requests, persisted intermediate summaries.
        batches, batch, size = [], [], 0
        expanded = []
        for segment in material:
            raw = segment["text"]
            while raw:
                part = raw[:2500]
                expanded.append(dict(segment, text=part))
                raw = raw[len(part) :]
        for segment in expanded:
            if batch and size + context.cost(segment["text"]) > 12000:
                batches.append(batch)
                batch, size = [], 0
            batch.append(segment)
            size += context.cost(segment["text"])
        if batch:
            batches.append(batch)
        if len(batches) <= 1 and not snap["coverage"]["truncated"]:
            await self.stream(job)
            return
        notes = list(snap.get("summary_notes", []))
        for index, batch in enumerate(batches):
            if index < len(notes):
                continue
            messages, _ = context.prepare(
                batch,
                [],
                [],
                "Extract all key concepts, questions, conclusions and uncertainties with source IDs.",
                f"Output language: {snap['language']}",
                require_all=True,
            )
            notes.append(await self.stream(job, messages, checkpoint=False))
            with self.db.tx() as tx:
                current = tx.get("jobs", job["id"])
                current["snapshot"]["summary_notes"] = notes
                current["progress"] = dict(
                    phase="extracting", completed=index + 1, total=len(batches), unit="sections"
                )
                self.s.emit(tx, "jobs", tx.save("jobs", current))
        while sum(context.cost(n) for n in notes) > 22000:
            reduced, group, size = [], [], 0
            for note in notes:
                if group and size + context.cost(note) > 12000:
                    reduced.append(
                        await self.stream(
                            job,
                            [
                                {"role": "system", "content": context.SYSTEM},
                                {
                                    "role": "user",
                                    "content": "Compress these section summaries, retaining evidence and uncertainties:\n"
                                    + "\n".join(group),
                                },
                            ],
                            checkpoint=False,
                        )
                    )
                    group, size = [], 0
                group.append(note)
                size += context.cost(note)
            if group:
                reduced.append(
                    await self.stream(
                        job,
                        [
                            {"role": "system", "content": context.SYSTEM},
                            {
                                "role": "user",
                                "content": "Compress these section summaries to at most 1500 words:\n"
                                + "\n".join(group),
                            },
                        ],
                        checkpoint=False,
                    )
                )
            if sum(map(context.cost, reduced)) >= sum(map(context.cost, notes)):
                raise Fault("summary_budget", "提炼后内容仍超出合并预算，请使用更简洁的模型输出", 503, True)
            notes = reduced
        with self.db.tx() as tx:
            current = tx.get("jobs", job["id"])
            current["progress"] = dict(
                phase="merging", completed=len(batches), total=len(batches), unit="sections"
            )
            self.s.emit(tx, "jobs", tx.save("jobs", current))
        gap_description = json.dumps(
            dict(count=len(snap["coverage"]["gaps"]), ranges=snap["coverage"]["gaps"][:20]),
            ensure_ascii=False,
        )
        await self.stream(
            job,
            [
                {"role": "system", "content": context.SYSTEM + f" Output language: {snap['language']}."},
                {
                    "role": "user",
                    "content": snap["messages"][-1]["content"]
                    + "\nCoverage gaps: "
                    + gap_description
                    + "\n"
                    + "\n".join(notes),
                },
            ],
        )

    def register_chunk(self, tx, source, record, path):
        if tx.all("audio_chunks", source_id=source["id"], ordinal=record["ordinal"]):
            return
        tx.save(
            "audio_chunks",
            dict(
                id=uid(),
                source_id=source["id"],
                ordinal=record["ordinal"],
                start_ms=record["start_ms"],
                end_ms=record["end_ms"],
                relative_path=str(path.relative_to(self.db.root)),
                checksum=record["checksum"],
                state="pending",
                attempts=0,
                error=None,
            ),
            True,
        )

    async def run_transcribe_source(self, job):
        with self.db.tx() as tx:
            source = tx.get("audio_sources", job["source_id"])
            source["transcription_state"] = "running"
            self.s.emit(tx, "audio_sources", tx.save("audio_sources", source))
        directory = self.db.path(f"lessons/{source['lesson_id']}/{source['id']}")
        if source["kind"] == "upload":
            records = await self.local_work(
                audio.split_file,
                directory / "normalized.wav",
                directory / "chunks",
                source["settings_snapshot"]["transcription"],
            )
            with self.db.tx() as tx:
                for record in records:
                    self.register_chunk(tx, source, record, directory / "chunks" / record["filename"])
            await self.encode(source)
        failures = 0
        attempted = set()
        while True:
            with self.db.tx() as tx:
                source = tx.get("audio_sources", job["source_id"])
                chunks = sorted(tx.all("audio_chunks", source_id=source["id"]), key=lambda c: c["ordinal"])
                pending = [c for c in chunks if c["state"] != "completed" and c["id"] not in attempted]
            if not pending:
                if source["capture_state"] in ("preparing", "capturing", "finalizing"):
                    await asyncio.sleep(0.15)
                    continue
                break
            chunk = pending[0]
            attempted.add(chunk["id"])
            with self.db.tx() as tx:
                chunk["attempts"] += 1
                tx.save("audio_chunks", chunk)
            try:
                data = await asyncio.to_thread(self.db.path(chunk["relative_path"]).read_bytes)
                try:
                    async with asyncio.timeout(60):
                        words = await self.stream(job, audio_bytes=data, checkpoint=False)
                except TimeoutError:
                    raise Fault("provider_timeout", "持续识别故障已超过 60 秒，请稍后补识别", 503) from None
                with self.db.tx() as tx:
                    chunk.update(state="completed", error=None)
                    tx.save("audio_chunks", chunk)
                    source = tx.get("audio_sources", source["id"])
                    source["transcribed_ms"] += chunk["end_ms"] - chunk["start_ms"]
                    self.s.emit(tx, "audio_sources", tx.save("audio_sources", source))
                    # Silence is successfully processed but creates no empty transcript.
                    if words.strip():
                        segment = tx.save(
                            "transcript_segments",
                            dict(
                                id=uid(),
                                lesson_id=source["lesson_id"],
                                source_id=source["id"],
                                chunk_id=chunk["id"],
                                source_ordinal=source["ordinal"],
                                ordinal=chunk["ordinal"],
                                start_ms=chunk["start_ms"],
                                end_ms=chunk["end_ms"],
                                text=words.strip(),
                                model=job["snapshot"]["model"],
                            ),
                            True,
                        )
                        self.s.bump(tx, source["lesson_id"])
                        self.s.emit(tx, "transcript_segments", segment, "transcript.created")
                        lesson = self.s.lesson(tx, source["lesson_id"])
                        if lesson["automation_mode"] != "transcribe_only":
                            self.s.detect(tx, lesson["id"], [segment], True, job["id"])
                    current = tx.get("jobs", job["id"])
                    current["progress"] = dict(
                        phase="transcribing",
                        completed=len(
                            [
                                c
                                for c in tx.all("audio_chunks", source_id=source["id"])
                                if c["state"] == "completed"
                            ]
                        ),
                        total=None if source["capture_state"] == "capturing" else len(chunks),
                        unit="chunks",
                    )
                    self.s.emit(tx, "jobs", tx.save("jobs", current))
                failures = 0
            except Fault as exc:
                with self.db.tx() as tx:
                    chunk.update(state="failed", error=exc.public())
                    tx.save("audio_chunks", chunk)
                failures += 1
                if not exc.retryable or failures >= 2:
                    raise
        with self.db.tx() as tx:
            source = tx.get("audio_sources", source["id"])
            chunks = tx.all("audio_chunks", source_id=source["id"])
            source["gap_ranges"] = [
                g
                for g in source["gap_ranges"]
                if g["reason"]
                in (
                    "possible_unflushed_audio",
                    "capture_overflow",
                    "storage_unavailable",
                    "audio_disconnected",
                )
            ] + [
                dict(start_ms=c["start_ms"], end_ms=c["end_ms"], reason="transcription_failed")
                for c in chunks
                if c["state"] != "completed"
            ]
            source["transcription_state"] = "partial" if source["gap_ranges"] else "completed"
            self.s.emit(tx, "audio_sources", tx.save("audio_sources", source))
            if source["gap_ranges"]:
                raise Fault("transcription_partial", "部分区间识别失败，可以补识别", 503, True)

    def transcription_snapshot(self, tx, source, options):
        config = self.s.configured(tx)
        # Uploading is local and works before configuration. Freeze model settings
        # when its first analysis is accepted; subsequent retries keep this snapshot.
        if source["kind"] == "upload" and source["transcription_state"] == "idle":
            source["settings_snapshot"] = config["values"]
            source["settings_revision"] = config["revision"]
            source["credential_revision"] = tx.get("credentials", "dashscope")["revision"]
            tx.save("audio_sources", source)
        return dict(
            settings=source["settings_snapshot"],
            settings_revision=source["settings_revision"],
            credential_revision=tx.get("credentials", "dashscope")["revision"],
            model=source["settings_snapshot"]["models"]["transcription"],
            messages=[
                {
                    "role": "user",
                    "content": "Transcribe only the speech heard in this audio, verbatim, preserving the spoken languages, including mixed Chinese and English. Never answer or summarize speech. Return empty text for silence. Use [unclear] where speech is unintelligible. Expected language: "
                    + source["settings_snapshot"]["transcription"]["language"],
                }
            ],
            **options,
        )

    async def run_start_source(self, job):
        with self.db.tx() as tx:
            source = tx.get("audio_sources", job["source_id"])
            if source["capture_state"] != "preparing":
                return
        stream = await self.hardware.open(source["kind"], job["snapshot"]["device_id"])
        with self.db.tx() as tx:
            source = tx.get("audio_sources", source["id"])
            stopped = source["capture_state"] != "preparing"
            if not stopped:
                source["started_at"] = now()
                minutes = job["snapshot"].get("auto_stop_minutes")
                source["stop_at"] = (
                    (datetime.now(UTC) + timedelta(minutes=minutes or 240)).isoformat().replace("+00:00", "Z")
                )
                source["capture_state"] = "capturing"
                self.s.emit(tx, "audio_sources", tx.save("audio_sources", source))
                current = tx.get("jobs", job["id"])
                current["slot"] = None
                tx.save("jobs", current)
                self.s.job(
                    tx,
                    "transcribe_source",
                    source["lesson_id"],
                    source["id"],
                    snapshot=self.transcription_snapshot(tx, source, {"generate_summary": False}),
                    slot="audio",
                )
        if stopped:
            await stream.close()
            return
        self.captures[source["id"]] = asyncio.create_task(self.capture(source, stream))

    async def capture(self, source, stream):
        segmenter = audio.Segmenter(
            source["settings_snapshot"]["transcription"]["max_chunk_seconds"],
            source["settings_snapshot"]["transcription"]["silence_ms"],
        )
        directory = self.db.path(f"lessons/{source['lesson_id']}/{source['id']}/chunks")
        sample, ordinal, error = 0, 1, None
        try:
            while not self.closing:
                with self.db.tx() as tx:
                    current = tx.get("audio_sources", source["id"])
                    if current["capture_state"] != "capturing":
                        break
                    if current["stop_at"] <= now():
                        self.s.stop(tx, current)
                        break
                pcm = await stream.read()
                if not pcm:
                    continue
                values = np.frombuffer(pcm, dtype="<i2").astype(float) / 32768
                peak = float(np.max(np.abs(values)))
                level = float(20 * np.log10(max(0.00001, np.sqrt(np.mean(values**2)))))
                self.publish(
                    "audio.level",
                    source_id=source["id"],
                    lesson_id=source["lesson_id"],
                    db=level,
                    peak=peak,
                    clipping=peak >= 0.99,
                )
                if chunk := segmenter.feed(pcm):
                    audio.storage_check(self.db.root)
                    record = await asyncio.to_thread(audio.save_chunk, directory, ordinal, sample, chunk)
                    sample += len(chunk) // 2
                    with self.db.tx() as tx:
                        self.register_chunk(tx, source, record, directory / record["filename"])
                        current = tx.get("audio_sources", source["id"])
                        current.update(
                            captured_ms=sample * 1000 // audio.RATE, duration_ms=sample * 1000 // audio.RATE
                        )
                        self.s.emit(tx, "audio_sources", tx.save("audio_sources", current))
                    ordinal += 1
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, Fault)
                else Fault("storage_unavailable", "音频写盘失败，采集已停止", 503)
            )
        finally:
            await stream.close()
            try:
                if tail := segmenter.flush():
                    record = await asyncio.to_thread(audio.save_chunk, directory, ordinal, sample, tail)
                    sample += len(tail) // 2
                    with self.db.tx() as tx:
                        self.register_chunk(tx, source, record, directory / record["filename"])
            except Exception:
                error = Fault("storage_unavailable", "尾部音频保存失败", 503)
            with self.db.tx() as tx:
                current = tx.get("audio_sources", source["id"])
                current.update(
                    capture_state="interrupted" if error else "finalizing",
                    stopped_at=now(),
                    duration_ms=sample * 1000 // audio.RATE,
                    captured_ms=sample * 1000 // audio.RATE,
                )
                if error:
                    current["error"] = error.public()
                    current["gap_ranges"].append(
                        dict(
                            start_ms=current["captured_ms"],
                            end_ms=current["captured_ms"] + 100,
                            reason=error.code,
                        )
                    )
                current = tx.save("audio_sources", current)
                self.s.emit(tx, "audio_sources", current)
                if not any(
                    j["kind"] == "finalize_source" and j.get("source_id") == source["id"]
                    for j in self.s.active(tx)
                ):
                    self.s.job(tx, "finalize_source", source["lesson_id"], source["id"])
            self.captures.pop(source["id"], None)

    async def encode(self, source):
        with self.db.tx() as tx:
            chunks = sorted(tx.all("audio_chunks", source_id=source["id"]), key=lambda c: c["ordinal"])
            if any(
                a["role"] == "playback" and a["state"] in ("available", "partial")
                for a in tx.all("audio_assets", source_id=source["id"])
            ):
                return
        if not chunks:
            return
        relative = f"lessons/{source['lesson_id']}/{source['id']}/playback.mp3"
        path = self.db.path(relative)
        await self.local_work(audio.encode_mp3, [self.db.path(c["relative_path"]) for c in chunks], path)
        checksum = await asyncio.to_thread(audio.file_hash, path)
        with self.db.tx() as tx:
            tx.save(
                "audio_assets",
                dict(
                    id=uid(),
                    source_id=source["id"],
                    role="playback",
                    relative_path=relative,
                    checksum=checksum,
                    bytes=path.stat().st_size,
                    duration_ms=source["duration_ms"],
                    mime_type="audio/mpeg",
                    state="partial" if source["capture_state"] == "interrupted" else "available",
                ),
                True,
            )
            self.s.emit(tx, "audio_sources", tx.get("audio_sources", source["id"]))

    async def run_finalize_source(self, job):
        while True:
            with self.db.tx() as tx:
                source = tx.get("audio_sources", job["source_id"])
            with self.db.tx() as tx:
                preparing = any(
                    j["kind"] == "start_source" and j.get("source_id") == source["id"]
                    for j in self.s.active(tx)
                )
            if not preparing and source["id"] not in self.captures and source["capture_state"] != "capturing":
                break
            await asyncio.sleep(0.1)
        await self.encode(source)
        with self.db.tx() as tx:
            source = tx.get("audio_sources", job["source_id"])
            if source["capture_state"] != "interrupted":
                source["capture_state"] = "ready"
                source["error"] = None
            source["stopped_at"] = source["stopped_at"] or now()
            self.s.emit(tx, "audio_sources", tx.save("audio_sources", source))

    async def run_test_audio(self, job):
        stream = await self.hardware.open(job["snapshot"]["kind"], job["snapshot"]["device_id"])
        end = time.monotonic() + 5
        try:
            while time.monotonic() < end:
                pcm = await stream.read()
                if pcm:
                    values = np.frombuffer(pcm, dtype="<i2").astype(float) / 32768
                    peak = float(np.max(np.abs(values)))
                    self.publish(
                        "audio.level",
                        job_id=job["id"],
                        db=float(20 * np.log10(max(0.00001, np.sqrt(np.mean(values**2))))),
                        peak=peak,
                        clipping=peak >= 0.99,
                    )
        finally:
            await stream.close()

    async def run_test_provider(self, job):
        start = time.monotonic()
        data = None
        if job["snapshot"]["capability"] == "transcription":
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(audio.RATE)
                f.writeframes(b"\x00\x00" * audio.RATE)
            data = buffer.getvalue()
        await self.stream(job, audio_bytes=data, checkpoint=False)
        with self.db.tx() as tx:
            current = tx.get("jobs", job["id"])
            current["progress"] = dict(
                phase="completed",
                completed=1,
                total=1,
                unit="test",
                latency_ms=round((time.monotonic() - start) * 1000),
            )
            tx.save("jobs", current)

    async def run_delete_lesson(self, job):
        path = self.db.path("lessons/" + job["lesson_id"])
        if path.exists():
            try:
                await asyncio.to_thread(shutil.rmtree, path)
            except OSError:
                raise Fault("cleanup_failed", "文件清理未完成，请检查权限后重试此任务", 503, True) from None
        with self.db.tx() as tx:
            lesson = tx.get("lessons", job["lesson_id"], False)
            if lesson:
                tx.delete("lessons", lesson["id"])
                tx.emit(
                    "lesson.deleted",
                    dict(id=lesson["id"], revision=lesson["revision"] + 1, lifecycle="deleted"),
                    lesson["id"],
                )
                self.s.emit(tx, "courses", tx.get("courses", lesson["course_id"]))

    async def close(self):
        self.closing = True
        if self.loop_task:
            await self.loop_task
        if self.captures:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*list(self.captures.values()), return_exceptions=True), 10
                )
            except TimeoutError:
                pass
        # Finalize saved local audio even though the normal dispatcher is now stopped.
        with self.db.tx() as tx:
            finalize = [
                j for j in self.s.active(tx) if j["kind"] == "finalize_source" and j["id"] not in self.tasks
            ]
        for job in finalize:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.execute(job), 10)
        pending = list(self.tasks.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
