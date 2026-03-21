"""WebSocket 路由 - 实时通信"""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from class_copilot.logger import ws_logger
from class_copilot.config import settings
from class_copilot.services.session_manager import session_manager

router = APIRouter()

# 活跃的 WebSocket 连接
_active_connections: list[WebSocket] = []


async def broadcast_worker():
    """后台广播工作者，从队列中取消息广播到所有连接"""
    while True:
        try:
            message = await session_manager.ws_broadcast_queue.get()
            dead = []
            for ws in _active_connections:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)

            for ws in dead:
                _active_connections.remove(ws)

        except asyncio.CancelledError:
            break
        except Exception as e:
            ws_logger.error("广播异常: {}", e)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 连接端点"""
    await websocket.accept()
    _active_connections.append(websocket)
    ws_logger.info("WebSocket 连接建立, 当前连接数: {}", len(_active_connections))

    # 发送当前状态
    await websocket.send_json({
        "type": "status",
        "data": {
            "status": session_manager.status,
            "session_id": session_manager.current_session_id,
            "course_name": session_manager.current_course_name,
            "is_listening": session_manager.is_listening,
            "filter_mode": settings.llm_filter_mode,
        },
    })

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            await _handle_client_message(message)

    except WebSocketDisconnect:
        ws_logger.info("WebSocket 连接断开")
    except Exception as e:
        ws_logger.error("WebSocket 异常: {}", e)
    finally:
        if websocket in _active_connections:
            _active_connections.remove(websocket)


async def _handle_client_message(message: dict):
    """处理来自客户端的消息"""
    msg_type = message.get("type", "")
    data = message.get("data", {})

    ws_logger.debug("收到客户端消息: type={}", msg_type)

    if msg_type == "start_listening":
        course_name = data.get("course_name", "")
        await session_manager.start_listening(course_name)

    elif msg_type == "stop_listening":
        await session_manager.stop_listening()

    elif msg_type == "manual_detect":
        await session_manager.manual_detect()

    elif msg_type == "chat":
        user_question = data.get("question", "")
        model = data.get("model")
        think_mode = data.get("think_mode", False)
        if user_question:
            asyncio.create_task(
                session_manager.chat(user_question, model, think_mode)
            )

    elif msg_type == "toggle_filter_mode":
        await session_manager.toggle_filter_mode()

    elif msg_type == "manual_refine":
        await session_manager.manual_refine()

    elif msg_type == "mark_teacher":
        speaker_label = data.get("speaker_label", "")
        teacher_name = data.get("teacher_name", "教师")
        if speaker_label:
            from class_copilot.database import async_session
            from class_copilot.models.models import Voiceprint, Session, Course
            from sqlalchemy import select

            async with async_session() as db:
                result = await db.execute(
                    select(Session).where(Session.id == session_manager.current_session_id)
                )
                session = result.scalar_one_or_none()
                if session:
                    vp = Voiceprint(
                        course_id=session.course_id,
                        teacher_name=teacher_name,
                        speaker_label=speaker_label,
                    )
                    db.add(vp)
                    await db.commit()

    elif msg_type == "force_answer":
        question_text = data.get("question", "")
        if question_text:
            detection = {
                "question": question_text,
                "confidence": 1.0,
                "context": await session_manager._get_session_context(),
            }
            await session_manager._handle_detected_question(detection, "forced")

    else:
        ws_logger.warning("未知消息类型: {}", msg_type)
