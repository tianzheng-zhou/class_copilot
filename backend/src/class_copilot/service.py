from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

from . import context
from .domain import Fault, digest, now, uid
from .persistence import question_segments

PUBLIC_TABLES = {
    "course": "courses",
    "lesson": "lessons",
    "source": "audio_sources",
    "transcript": "transcript_segments",
    "question": "questions",
    "answer_version": "answer_versions",
    "answer": "answer_versions",
    "chat_turn": "chat_turns",
    "chat_reply": "chat_replies",
    "summary": "summary_versions",
    "summary_version": "summary_versions",
    "job": "jobs",
}


class Service:
    def __init__(self, db):
        self.db = db

    def lesson(self, tx, identity, writable=True):
        lesson = tx.get("lessons", identity)
        if writable and lesson["lifecycle"] != "ready":
            raise Fault("lesson_deleting", "课堂正在删除，可在任务中重试清理")
        return lesson

    def settings(self, tx):
        return tx.get("settings", "main")

    def configured(self, tx):
        setting = self.settings(tx)
        if not setting["values"]["provider"]["region"] or not setting["values"]["provider"]["base_url"]:
            raise Fault("provider_not_configured", "请在设置中填写工作空间区域与服务地址", 503)
        self.db.secret(tx)
        return setting

    def active(self, tx, lesson_id=None):
        return tx.active_jobs(lesson_id)

    def audio_slot(self, tx):
        for j in self.active(tx):
            if j.get("slot") == "audio":
                return self.public(tx, "jobs", j)
        return None

    def bump(self, tx, lesson_id):
        lesson = tx.get("lessons", lesson_id)
        # Content changes must not invalidate metadata If-Match.
        revision = lesson["revision"]
        lesson["content_revision"] += 1
        lesson["revision"] = revision - 1
        lesson = tx.save("lessons", lesson)
        tx.emit("lesson.updated", self.public(tx, "lessons", lesson), lesson_id)

    def public(self, tx, table, obj):
        value = {
            k: v
            for k, v in obj.items()
            if k
            not in (
                "snapshot",
                "slot",
                "normalized_name",
                "relative_path",
                "secret",
                "history",
                "settings_snapshot",
                "credential_revision",
                "dedup_key",
                "chunk_id",
                "checksum",
                "request_hash",
            )
        }
        if table == "courses":
            value["lesson_count"] = len(tx.all("lessons", course_id=obj["id"]))
        elif table == "credentials":
            value = dict(
                id="dashscope", set=bool(obj["secret"]), masked_value=obj["mask"], revision=obj["revision"]
            )
        elif table == "settings":
            value = dict(
                obj["values"],
                revision=obj["revision"],
                id="main",
                effective={
                    "audio": "next_source",
                    "transcription": "next_source",
                    "generation": "next_job",
                    "automation": "new_lesson",
                },
            )
        elif table == "lessons":
            course = tx.get("courses", obj["course_id"])
            sources = tx.all("audio_sources", lesson_id=obj["id"])
            sums = tx.all("summary_versions", lesson_id=obj["id"])
            value.update(
                course_name=course["name"],
                display_title=obj.get("custom_title") or f"{course['name']} · {obj['created_at']}",
                source_count=len(sources),
                transcript_count=len(tx.all("transcript_segments", lesson_id=obj["id"])),
                question_count=len(tx.all("questions", lesson_id=obj["id"])),
                active_jobs=[self.public(tx, "jobs", j) for j in self.active(tx, obj["id"])],
                audio_activity=next(
                    (
                        s["capture_state"]
                        for s in sources
                        if s["capture_state"] in ("preparing", "capturing", "finalizing")
                    ),
                    None,
                ),
                latest_summary_id=sums[-1]["id"] if sums else None,
            )
        elif table == "audio_sources":
            value["assets"] = [
                self.public(tx, "audio_assets", a) for a in tx.all("audio_assets", source_id=obj["id"])
            ]
            value["active_job_ids"] = [j["id"] for j in self.active(tx) if j.get("source_id") == obj["id"]]
        elif table == "audio_assets":
            value["url"] = f"/api/v1/assets/{obj['id']}/content"
        elif table == "questions":
            value["answer_versions"] = [
                self.public(tx, "answer_versions", a)
                for a in tx.all("answer_versions", question_id=obj["id"])
            ]
        elif table == "chat_turns":
            replies = [self.public(tx, "chat_replies", a) for a in tx.all("chat_replies", turn_id=obj["id"])]
            value["replies"] = replies
            value["selected_reply_id"] = next(
                (r["id"] for r in reversed(replies) if r["state"] == "completed"), None
            )
        elif table == "summary_versions":
            material = self.material(tx, obj["lesson_id"], obj["include_chat"])
            value["is_stale"] = obj["content_signature"] != context.signature(*material)
        return value

    def emit(self, tx, table, obj, kind=None):
        typ = next((k for k, v in PUBLIC_TABLES.items() if v == table), table)
        if typ == "answer_version":
            typ = "answer"
        lesson_id = obj.get("lesson_id")
        if table == "answer_versions":
            lesson_id = tx.get("questions", obj["question_id"])["lesson_id"]
        elif table == "chat_replies":
            lesson_id = tx.get("chat_turns", obj["turn_id"])["lesson_id"]
        tx.emit(kind or typ + ".updated", self.public(tx, table, obj), lesson_id)

    def page(self, tx, table, items, cursor=None, limit=50, filters=None, latest=True):
        if not 1 <= limit <= 200:
            raise Fault("validation_error", "limit 必须为 1–200", 422)
        binding = digest([table, filters or {}])
        if table == "transcript_segments":

            def key(i):
                return (i["source_ordinal"], i["ordinal"], i["id"])
        elif table in ("audio_sources", "chat_turns"):

            def key(i):
                return (i["ordinal"], i["id"])
        else:

            def key(i):
                return (i["created_at"], i["id"])

        ordered = sorted(items, key=key, reverse=True)
        total = len(ordered)
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor))
                if decoded["binding"] != binding:
                    raise ValueError()
                boundary = tuple(decoded["before"])
                ordered = [i for i in ordered if key(i) < boundary]
            except (ValueError, KeyError, TypeError):
                raise Fault("validation_error", "分页游标无效或筛选条件已改变", 422) from None
        selected = ordered[:limit]
        next_cursor = (
            base64.urlsafe_b64encode(
                json.dumps(dict(binding=binding, before=key(selected[-1]))).encode()
            ).decode()
            if len(ordered) > limit
            else None
        )
        if latest:
            selected.reverse()
        return dict(items=[self.public(tx, table, i) for i in selected], total=total, next_cursor=next_cursor)

    def material(self, tx, lesson_id, include_chat=False, before=None):
        segments = sorted(
            tx.all("transcript_segments", lesson_id=lesson_id),
            key=lambda s: (s["source_ordinal"], s["ordinal"]),
        )
        questions = tx.all("questions", lesson_id=lesson_id)
        answers = []
        for question in questions:
            successful = [
                a for a in tx.all("answer_versions", question_id=question["id"]) if a["state"] == "completed"
            ]
            if successful:
                answers.append(successful[-1])
        turns = [
            self.public(tx, "chat_turns", t)
            for t in tx.all("chat_turns", lesson_id=lesson_id)
            if include_chat and (before is None or t["ordinal"] < before)
        ]
        gaps = [
            dict(source_id=s["id"], **g)
            for s in tx.all("audio_sources", lesson_id=lesson_id)
            for g in s["gap_ranges"]
        ]
        for question in questions:
            versions = tx.all("answer_versions", question_id=question["id"])
            if not any(a["state"] == "completed" for a in versions):
                for segment in segments:
                    if segment["id"] in question["segment_ids"]:
                        gaps.append(
                            dict(
                                source_id=segment["source_id"],
                                start_ms=segment["start_ms"],
                                end_ms=segment["end_ms"],
                                reason="answer_unavailable",
                            )
                        )
        return segments, questions, answers, turns, gaps

    def selected(self, tx, lesson_id, identities):
        segments = tx.all("transcript_segments", lesson_id=lesson_id)
        chosen = [s for s in segments if s["id"] in identities]
        if len(chosen) != len(set(identities)) or not chosen:
            raise Fault("invalid_selection", "请选择本课堂有效的转写片段", 422)
        return sorted(chosen, key=lambda s: (s["source_ordinal"], s["ordinal"]))

    def job(
        self,
        tx,
        kind,
        lesson_id=None,
        source_id=None,
        snapshot=None,
        resource=None,
        slot=None,
        retry_of=None,
        parent_id=None,
    ):
        if lesson_id and kind != "delete_lesson":
            self.lesson(tx, lesson_id)
        if slot:
            owner = next((j for j in self.active(tx) if j.get("slot") == slot), None)
            if owner:
                raise Fault(
                    "audio_busy" if slot == "audio" else "job_busy",
                    "已有任务正在处理，请等待或取消",
                    lesson_id=owner.get("lesson_id"),
                    job_id=owner["id"],
                )
        if len(self.active(tx)) >= 500:
            raise Fault("local_capacity_exceeded", "本地任务队列已满，请稍后重试", 429)
        job = tx.save(
            "jobs",
            dict(
                id=uid(),
                kind=kind,
                state="queued",
                lesson_id=lesson_id,
                source_id=source_id,
                snapshot=snapshot or {},
                resource=resource,
                slot=slot,
                retry_of=retry_of,
                parent_id=parent_id,
                progress=dict(phase="queued", completed=0, total=None, unit="steps"),
                started_at=None,
                finished_at=None,
                cancel_requested=False,
                error=None,
            ),
            True,
        )
        self.emit(tx, "jobs", job, "job.created")
        return job

    def snapshot_base(self, tx, lesson_id):
        settings = self.configured(tx)
        lesson = self.lesson(tx, lesson_id)
        return dict(
            settings=settings["values"],
            settings_revision=settings["revision"],
            credential_revision=tx.get("credentials", "dashscope")["revision"],
            basis_revision=lesson["content_revision"],
            automation_revision=lesson["automation_revision"],
        )

    def generation(
        self, tx, kind, lesson_id, options=None, question=None, turn=None, retry_snapshot=None, retry_of=None
    ):
        options = options or {}
        snapshot = retry_snapshot or self.snapshot_base(tx, lesson_id)
        settings = snapshot["settings"]
        role = options.get("model_role")
        model = (
            settings["models"]["chat_" + role]
            if role
            else settings["models"][
                {"generate_answer": "answer", "chat_reply": "chat_fast", "summarize_lesson": "summary"}[kind]
            ]
        )
        language = options.get("language") or settings["generation"]["language"]
        include_chat = options.get("include_chat", False)
        segments, questions, answers, turns, gaps = self.material(
            tx, lesson_id, kind == "chat_reply" or include_chat, turn["ordinal"] if turn else None
        )
        instruction = f"Output language: {language}. Format: Markdown. These are AI reference materials."
        if kind == "generate_answer":
            table, resource_type, parent, slot = (
                "answer_versions",
                "answer_version",
                {"question_id": question["id"]},
                "answer:" + question["id"],
            )
            style = options.get("style") or settings["generation"]["default_style"]
            instruction += f" Answer style: {style}."
            segments = self.selected(tx, lesson_id, question["segment_ids"])
            prompt = question["text"]
        elif kind == "chat_reply":
            table, resource_type, parent, slot = (
                "chat_replies",
                "chat_reply",
                {"turn_id": turn["id"]},
                "chat:" + lesson_id,
            )
            prompt = turn["user_content"]
        else:
            if not segments and not retry_snapshot:
                raise Fault("no_transcript", "尚无有效转写，无法生成课堂总结", 422)
            table, resource_type, parent, slot = (
                "summary_versions",
                "summary_version",
                {"lesson_id": lesson_id},
                "summary:" + lesson_id,
            )
            prompt = "Summarize key concepts, explanations, classroom questions and conclusions, uncertainties, and review suggestions. Leave unsupported sections empty. Report incomplete coverage."
        if retry_snapshot:
            messages, cover = snapshot["messages"], snapshot["coverage"]
            model, language = snapshot["model"], snapshot["language"]
        else:
            messages, cover = context.prepare(
                segments,
                turns,
                answers,
                prompt,
                instruction,
                require_all=kind == "generate_answer",
                gaps=gaps,
                questions=questions if kind != "generate_answer" else (),
            )
            snapshot.update(
                messages=messages,
                coverage=cover,
                model=model,
                language=language,
                options=options,
                segment_ids=[s["id"] for s in segments],
                thinking=options.get("thinking", False),
            )
            if kind == "summarize_lesson":
                snapshot["summary_material"] = [
                    dict(
                        id=s["id"],
                        source_id=s["source_id"],
                        ordinal=s["ordinal"],
                        start_ms=s["start_ms"],
                        end_ms=s["end_ms"],
                        text=s["text"],
                    )
                    for s in segments
                ]
                snapshot["summary_signature"] = context.signature(segments, questions, answers, turns, gaps)
                snapshot["summary_auxiliary"] = dict(questions=questions, answers=answers, turns=turns)
                snapshot["coverage"] = context.coverage(segments, turns, answers, gaps)
                cover = snapshot["coverage"]
        existing = tx.all(table, **parent)
        version = max((i.get("version", i.get("attempt", 0)) for i in existing), default=0) + 1
        identity = uid()
        job = self.job(
            tx,
            kind,
            lesson_id,
            snapshot=snapshot,
            resource=dict(type=resource_type, id=identity),
            slot=slot,
            retry_of=retry_of,
        )
        entity = dict(
            id=identity,
            **parent,
            content="",
            state="pending",
            model=model,
            job_id=job["id"],
            basis_revision=snapshot["basis_revision"],
            context_coverage=cover,
            error=None,
            finished_at=None,
        )
        if kind == "chat_reply":
            entity.update(attempt=version, thinking=snapshot.get("thinking", False))
        else:
            entity.update(version=version, language=language)
        if kind == "generate_answer":
            entity["style"] = (
                snapshot.get("options", {}).get("style") or settings["generation"]["default_style"]
            )
        if kind == "summarize_lesson":
            entity.update(
                include_chat=snapshot.get("options", {}).get("include_chat", False),
                content_signature=snapshot["summary_signature"],
            )
        entity = tx.save(table, entity, True)
        self.emit(tx, table, entity)
        return job, entity

    def detect(self, tx, lesson_id, segments, automatic=False, parent_id=None):
        snapshot = self.snapshot_base(tx, lesson_id)
        messages, cover = context.prepare(
            segments,
            [],
            [],
            'Find genuine classroom questions in the material. Return JSON: {"questions":[{"text":"...","confidence":0.9}]}. Return an empty array if none.',
            budget=8000,
            require_all=not automatic,
        )
        snapshot.update(
            messages=messages,
            coverage=cover,
            segment_ids=[s["id"] for s in segments],
            automatic=automatic,
            model=snapshot["settings"]["models"]["detection"],
        )
        return self.job(tx, "detect_questions", lesson_id, snapshot=snapshot, parent_id=parent_id)

    def question(self, tx, lesson_id, text, segments, origin, confidence=None):
        key = digest([lesson_id, text.strip().casefold(), sorted(s["id"] for s in segments)])
        old = next((q for q in tx.all("questions", lesson_id=lesson_id) if q["dedup_key"] == key), None)
        if old:
            return old, False
        q = tx.save(
            "questions",
            dict(
                id=uid(),
                lesson_id=lesson_id,
                text=text,
                origin=origin,
                confidence=confidence,
                segment_ids=[s["id"] for s in segments],
                dedup_key=key,
            ),
            True,
        )
        for s in segments:
            tx.conn.execute(question_segments.insert().values(question_id=q["id"], segment_id=s["id"]))
        self.bump(tx, lesson_id)
        self.emit(tx, "questions", q, "question.created")
        return q, True

    def accepted(self, tx, job, resource=None):
        return dict(job=self.public(tx, "jobs", job), resource=resource or job.get("resource"))

    def new_source(self, tx, lesson_id, kind, **extra):
        self.lesson(tx, lesson_id)
        settings = self.settings(tx)
        ordinal = max((s["ordinal"] for s in tx.all("audio_sources", lesson_id=lesson_id)), default=0) + 1
        source = dict(
            id=uid(),
            lesson_id=lesson_id,
            ordinal=ordinal,
            kind=kind,
            device_label=None,
            original_filename=None,
            capture_state="preparing",
            transcription_state="idle",
            settings_revision=settings["revision"],
            settings_snapshot=settings["values"],
            credential_revision=tx.get("credentials", "dashscope")["revision"],
            started_at=None,
            stopped_at=None,
            stop_at=None,
            duration_ms=0,
            captured_ms=0,
            transcribed_ms=0,
            gap_ranges=[],
            error=None,
        )
        source.update(extra)
        source = tx.save("audio_sources", source, True)
        self.emit(tx, "audio_sources", source, "source.created")
        return source

    def stop(self, tx, source):
        if source["capture_state"] not in ("preparing", "capturing", "finalizing"):
            return 200, dict(source=self.public(tx, "audio_sources", source), job=None)
        jobs = [
            j
            for j in self.active(tx)
            if j.get("source_id") == source["id"] and j["kind"] == "finalize_source"
        ]
        source["capture_state"] = "finalizing"
        source["stopped_at"] = now()
        source = tx.save("audio_sources", source)
        self.emit(tx, "audio_sources", source)
        if jobs:
            return 202, self.accepted(tx, jobs[0])
        job = self.job(tx, "finalize_source", source["lesson_id"], source["id"])
        return 202, self.accepted(tx, job)

    def revision(self, obj, header):
        if header is None:
            raise Fault("revision_required", "更新需要 If-Match 版本", 428)
        if header != f'"{obj["revision"]}"':
            raise Fault(
                "revision_conflict", "内容已在其他页面更新，请重新加载", 412, revision=obj["revision"]
            )

    def command(self, tx, key, method, path, body, action):
        request_hash = digest([method, path, body])
        saved = tx.get("idempotency_keys", key, False)
        if saved and saved["expires_at"] > now():
            if saved["request_hash"] != request_hash:
                raise Fault("idempotency_conflict", "同一命令标识不能用于不同操作")
            return saved["response_status"], saved["response_body"], True
        status, data = action()
        expires = (datetime.now(UTC) + timedelta(days=2)).isoformat().replace("+00:00", "Z")
        tx.save(
            "idempotency_keys",
            dict(
                id=key,
                request_hash=request_hash,
                response_status=status,
                response_body=data,
                expires_at=expires,
            ),
            saved is None,
        )
        return status, data, False
