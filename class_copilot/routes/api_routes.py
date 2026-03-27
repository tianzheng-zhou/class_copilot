"""REST API 路由 - 历史查询、设置、导出等"""

import asyncio
import io
import time
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from class_copilot.database import get_db, async_session
from class_copilot.config import settings
from class_copilot.models.models import (
    Course, Session, Recording, Transcription, Question, Answer,
    ChatMessage, Voiceprint, SettingItem,
)
from class_copilot.services.encryption_service import encrypt_value, decrypt_value
from class_copilot.services.session_manager import session_manager
from class_copilot.services.oss_service import oss_service

router = APIRouter(prefix="/api")


# ──────────── Schemas ────────────

class CourseCreate(BaseModel):
    name: str
    language: str = "zh"
    hot_words: str = ""


class SettingUpdate(BaseModel):
    key: str
    value: str
    is_encrypted: bool = False


class ChatRequest(BaseModel):
    question: str
    model: str | None = None
    think_mode: bool = False


# ──────────── 课程 ────────────

@router.get("/courses")
async def list_courses():
    async with async_session() as db:
        result = await db.execute(select(Course).order_by(Course.updated_at.desc()))
        courses = result.scalars().all()
        return [{"id": c.id, "name": c.name, "language": c.language, "hot_words": c.hot_words} for c in courses]


@router.post("/courses")
async def create_course(data: CourseCreate):
    async with async_session() as db:
        course = Course(name=data.name, language=data.language, hot_words=data.hot_words)
        db.add(course)
        await db.commit()
        return {"id": course.id, "name": course.name}


@router.put("/courses/{course_id}")
async def update_course(course_id: str, data: CourseCreate):
    async with async_session() as db:
        result = await db.execute(select(Course).where(Course.id == course_id))
        course = result.scalar_one_or_none()
        if not course:
            raise HTTPException(status_code=404, detail="课程不存在")
        course.name = data.name
        course.language = data.language
        course.hot_words = data.hot_words
        await db.commit()
        return {"id": course.id}


# ──────────── 历史会话 ────────────

@router.get("/sessions")
async def list_sessions(date_from: str | None = None, date_to: str | None = None):
    async with async_session() as db:
        query = (
            select(Session)
            .options(selectinload(Session.course))
            .order_by(Session.started_at.desc())
        )
        if date_from:
            query = query.where(Session.date >= date_from)
        if date_to:
            query = query.where(Session.date <= date_to)
        result = await db.execute(query)
        sessions = result.scalars().all()
        return [{
            "id": s.id,
            "custom_name": s.custom_name,
            "course_name": s.course.name if s.course else "",
            "date": s.date,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "status": s.status,
            "refinement_status": s.refinement_status,
        } for s in sessions]


@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: str):
    async with async_session() as db:
        # 会话基本信息
        result = await db.execute(
            select(Session).options(selectinload(Session.course)).where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        # 转写记录
        trans_result = await db.execute(
            select(Transcription)
            .where(Transcription.session_id == session_id)
            .where(Transcription.is_final == True)
            .order_by(Transcription.sequence)
        )
        transcriptions = trans_result.scalars().all()

        # 问题和答案
        q_result = await db.execute(
            select(Question)
            .options(selectinload(Question.answers))
            .where(Question.session_id == session_id)
            .order_by(Question.created_at.desc())
        )
        questions = q_result.scalars().all()

        # 主动提问
        chat_result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        chat_messages = chat_result.scalars().all()

        # 将相对时间转为绝对 epoch 时间（本地时间）
        session_epoch = time.mktime(session.started_at.timetuple()) if session.started_at else 0

        return {
            "session": {
                "id": session.id,
                "course_name": session.course.name if session.course else "",
                "date": session.date,
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                "status": session.status,
                "refinement_status": session.refinement_status,
            },
            "transcriptions": [{
                "id": t.id,
                "sequence": t.sequence,
                "text": t.best_text,
                "realtime_text": t.realtime_text,
                "refined_text": t.refined_text,
                "speaker_label": t.speaker_label,
                "is_teacher": t.is_teacher,
                "refinement_status": t.refinement_status,
                "start_time": (session_epoch + t.start_time) if session_epoch and t.start_time else t.start_time,
                "end_time": (session_epoch + t.end_time) if session_epoch and t.end_time else t.end_time,
            } for t in transcriptions],
            "questions": [{
                "id": q.id,
                "question_text": q.question_text,
                "source": q.source,
                "confidence": q.confidence,
                "created_at": q.created_at.isoformat(),
                "answers": [{
                    "id": a.id,
                    "answer_type": a.answer_type,
                    "content": a.content,
                    "is_refined_update": a.is_refined_update,
                } for a in q.answers],
            } for q in questions],
            "chat_messages": [{
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "model_used": m.model_used,
                "created_at": m.created_at.isoformat(),
            } for m in chat_messages],
        }


@router.put("/sessions/{session_id}/rename")
async def rename_session(session_id: str, data: dict):
    """重命名会话"""
    new_name = data.get("name", "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="名称不能为空")
    if len(new_name) > 200:
        raise HTTPException(status_code=400, detail="名称过长（最多200字）")

    async with async_session() as db:
        result = await db.execute(
            select(Session).where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        session.custom_name = new_name
        await db.commit()

    return {"status": "renamed", "custom_name": new_name}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    async with async_session() as db:
        # 获取相关录音文件
        result = await db.execute(
            select(Recording).where(Recording.session_id == session_id)
        )
        recordings = result.scalars().all()

        # 删除录音文件
        for r in recordings:
            try:
                Path(r.file_path).unlink(missing_ok=True)
            except Exception:
                pass

        # 级联删除会话（数据库外键已设置 CASCADE）
        await db.execute(delete(Session).where(Session.id == session_id))
        await db.commit()

    return {"status": "deleted"}


# ──────────── 导出 ────────────

@router.get("/sessions/{session_id}/export")
async def export_session(session_id: str):
    """导出会话为 Markdown"""
    detail = await get_session_detail(session_id)
    session_info = detail["session"]

    lines = [
        f"# 课堂记录 - {session_info['course_name']}",
        f"",
        f"**日期**: {session_info['date']}",
        f"**开始时间**: {session_info['started_at']}",
        f"**结束时间**: {session_info['ended_at'] or '进行中'}",
        f"",
        f"---",
        f"",
        f"## 转写记录",
        f"",
    ]

    for t in detail["transcriptions"]:
        role = "👨‍🏫 教师" if t["is_teacher"] else f"🗣️ {t['speaker_label']}"
        lines.append(f"**{role}**: {t['text']}")
        lines.append("")

    if detail["questions"]:
        lines.extend(["---", "", "## 检测到的问题与答案", ""])
        for q in detail["questions"]:
            source_icon = {"auto": "🔍", "manual": "✋", "forced": "💬", "refined": "🔄"}.get(q["source"], "")
            lines.append(f"### {source_icon} {q['question_text']}")
            lines.append("")
            for a in q["answers"]:
                label = "简洁版" if a["answer_type"] == "brief" else "展开版"
                lines.append(f"**{label}**: {a['content']}")
                lines.append("")

    if detail["chat_messages"]:
        lines.extend(["---", "", "## 主动提问记录", ""])
        for m in detail["chat_messages"]:
            if m["role"] == "user":
                lines.append(f"🙋 **你**: {m['content']}")
            else:
                lines.append(f"🤖 **AI**: {m['content']}")
            lines.append("")

    content = "\n".join(lines)
    return PlainTextResponse(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=class_{session_info['date']}.md"},
    )


@router.get("/sessions/{session_id}/export/audio")
async def export_session_audio(session_id: str):
    """导出会话录音为 MP3（多段录音打包为 ZIP）"""
    async with async_session() as db:
        # 获取会话信息
        result = await db.execute(
            select(Session).options(selectinload(Session.course)).where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        # 获取关联的录音文件
        rec_result = await db.execute(
            select(Recording)
            .where(Recording.session_id == session_id)
            .order_by(Recording.sequence_number)
        )
        recordings = rec_result.scalars().all()

    if not recordings:
        raise HTTPException(status_code=404, detail="该会话没有录音文件")

    course_name = session.course.name if session.course else "unknown"
    date_str = session.date or "unknown"
    base_name = f"class_{date_str}_{course_name}"

    # 筛选出实际存在的文件
    existing = []
    for r in recordings:
        p = Path(r.file_path)
        if p.exists() and p.is_file():
            existing.append(p)

    if not existing:
        raise HTTPException(status_code=404, detail="录音文件不存在（可能已被删除）")

    if len(existing) == 1:
        # 单个录音，直接返回 MP3
        from fastapi.responses import FileResponse
        return FileResponse(
            str(existing[0]),
            media_type="audio/mpeg",
            headers={"Content-Disposition": f"attachment; filename={base_name}.mp3"},
        )

    # 多段录音，打包为 ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for i, fp in enumerate(existing, 1):
            zf.write(fp, f"{base_name}_part{i}.mp3")
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={base_name}.zip"},
    )


# ──────────── 设置 ────────────

@router.get("/settings")
async def get_settings():
    async with async_session() as db:
        result = await db.execute(select(SettingItem))
        items = result.scalars().all()
        output = {}
        for item in items:
            if item.is_encrypted:
                try:
                    plain = decrypt_value(item.value)
                    preview = plain[:4] + "****" if len(plain) > 4 else "****"
                except Exception:
                    preview = "****"
                output[item.key] = preview
            else:
                output[item.key] = item.value
        return output


@router.put("/settings")
async def update_settings(data: SettingUpdate):
    async with async_session() as db:
        result = await db.execute(
            select(SettingItem).where(SettingItem.key == data.key)
        )
        item = result.scalar_one_or_none()

        value = encrypt_value(data.value) if data.is_encrypted else data.value

        if item:
            item.value = value
            item.is_encrypted = data.is_encrypted
        else:
            item = SettingItem(
                key=data.key, value=value, is_encrypted=data.is_encrypted
            )
            db.add(item)

        await db.commit()

    # 动态应用部分设置
    if data.key == "dashscope_api_key":
        real_value = data.value  # 使用原始值
        settings.dashscope_api_key = real_value
        session_manager.llm_service.update_api_key(real_value)
    elif data.key == "doubao_appid":
        settings.doubao_appid = data.value
    elif data.key == "doubao_access_token":
        settings.doubao_access_token = data.value
    elif data.key == "oss_access_key_id":
        settings.oss_access_key_id = data.value
    elif data.key == "oss_access_key_secret":
        settings.oss_access_key_secret = data.value

    return {"status": "updated"}


@router.get("/settings/runtime")
async def get_runtime_settings():
    """获取运行时设置（不含密钥）"""
    return {
        "language": settings.language,
        "enable_brief_answer": settings.enable_brief_answer,
        "enable_detailed_answer": settings.enable_detailed_answer,
        "enable_translation": settings.enable_translation,
        "enable_bilingual": settings.enable_bilingual,
        "enable_refinement": settings.enable_refinement,
        "refinement_strategy": settings.refinement_strategy,
        "refinement_interval_minutes": settings.refinement_interval_minutes,
        "llm_filter_mode": settings.llm_filter_mode,
        "asr_model": settings.asr_model,
        "asr_provider": settings.asr_provider,
        "refinement_provider": settings.refinement_provider,
        "auto_answer_model": settings.auto_answer_model,
        "llm_model_fast": settings.llm_model_fast,
        "llm_model_quality": settings.llm_model_quality,
        "oss_bucket_name": settings.oss_bucket_name,
        "oss_endpoint": settings.oss_endpoint,
        "oss_upload_prefix": settings.oss_upload_prefix,
        "oss_url_expiry_seconds": settings.oss_url_expiry_seconds,
    }


@router.put("/settings/runtime")
async def update_runtime_settings(data: dict):
    """更新运行时设置并持久化到数据库"""
    import json

    async with async_session() as db:
        for key, value in data.items():
            if not hasattr(settings, key):
                continue
            # 更新内存
            setattr(settings, key, value)
            # 持久化到数据库（JSON 编码以保留类型）
            str_value = json.dumps(value, ensure_ascii=False)
            result = await db.execute(
                select(SettingItem).where(SettingItem.key == key)
            )
            item = result.scalar_one_or_none()
            if item:
                item.value = str_value
                item.is_encrypted = False
            else:
                db.add(SettingItem(key=key, value=str_value, is_encrypted=False))
        await db.commit()

    return {"status": "updated"}


# ──────────── 录音文件访问 (供豆包离线转写下载) ────────────

@router.get("/recordings/{filename}")
async def serve_recording(filename: str):
    """提供录音文件下载（豆包离线 ASR 需通过 URL 访问音频文件）"""
    from fastapi.responses import FileResponse
    import re

    # 安全校验：仅允许安全的文件名字符
    if not re.match(r'^[\w\-\.]+$', filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = Path(settings.data_dir) / "recordings" / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Recording not found")

    # 确保路径不会逃逸出 recordings 目录
    try:
        file_path.resolve().relative_to((Path(settings.data_dir) / "recordings").resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(str(file_path), media_type="audio/mpeg")


# ──────────── 音频设备 ────────────

@router.get("/audio/devices")
async def list_audio_devices():
    return session_manager.audio_service.list_devices()


@router.put("/audio/device")
async def set_audio_device(data: dict):
    device_index = data.get("device_index")
    session_manager.audio_service.set_device(device_index)
    return {"status": "updated"}


@router.post("/audio/mic-monitor/start")
async def start_mic_monitor():
    """启动麦克风音量监控，音量数据通过 WebSocket 广播"""
    if session_manager.audio_service.is_monitoring:
        return {"status": "already_monitoring"}

    def on_level(db, peak, clipping):
        try:
            session_manager.ws_broadcast_queue.put_nowait({
                "type": "mic_level",
                "data": {
                    "db": round(db, 1),
                    "peak": round(peak / 32768.0, 4),
                    "clipping": clipping,
                },
            })
        except asyncio.QueueFull:
            pass

    session_manager.audio_service.start_mic_monitor(on_level)
    return {"status": "started"}


@router.post("/audio/mic-monitor/stop")
async def stop_mic_monitor():
    """停止麦克风音量监控"""
    session_manager.audio_service.stop_mic_monitor()
    return {"status": "stopped"}


# ──────────── 声纹管理 ────────────

@router.get("/voiceprints")
async def list_voiceprints():
    async with async_session() as db:
        result = await db.execute(
            select(Voiceprint).options(selectinload(Voiceprint.course))
        )
        vps = result.scalars().all()
        return [{
            "id": v.id,
            "course_name": v.course.name if v.course else "",
            "teacher_name": v.teacher_name,
            "speaker_label": v.speaker_label,
        } for v in vps]


@router.delete("/voiceprints/{vp_id}")
async def delete_voiceprint(vp_id: str):
    async with async_session() as db:
        await db.execute(delete(Voiceprint).where(Voiceprint.id == vp_id))
        await db.commit()
    return {"status": "deleted"}


# ──────────── 精修统计 ────────────

@router.get("/refinement/usage")
async def get_refinement_usage():
    return {
        "monthly_minutes": session_manager.refinement_service.monthly_usage_minutes,
    }


# ──────────── OSS 测试 ────────────

@router.post("/oss/test")
async def test_oss_connection():
    """测试 OSS 连接是否正常"""
    try:
        info = await oss_service.test_connection()
        return {"status": "ok", "info": info}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OSS 连接失败: {e}")
