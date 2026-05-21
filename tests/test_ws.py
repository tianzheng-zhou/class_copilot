from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient

from class_copilot.application.session import _paragraph_context


def test_websocket_status_and_chat_flow(app):
    client = TestClient(app)
    course = client.post("/api/courses", json={"name": "物理"}).json()
    settings = client.patch(
        "/api/settings",
        json={
            "asr_language": "bilingual",
            "auto_answer_language": "en",
            "auto_answer_model": "qwen3.5-plus",
            "chat_language": "bilingual",
        },
    )
    assert settings.status_code == 200
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "status"

        ws.send_json(
            {
                "type": "start_listening",
                "data": {
                    "course_id": course["id"],
                    "auto_stop_seconds": 0,
                    "auto_stop_label": "",
                },
            }
        )
        status = ws.receive_json()
        assert status["type"] == "status"
        assert status["data"]["status"] == "listening"
        assert app.state.fake_asr.started_languages[-1] == "bilingual"
        assert app.state.fake_asr.manual_turn_detection is True

        ws.send_json(
            {
                "type": "chat",
                "data": {"question": "解释一下", "model": "fast", "enable_thinking": True},
            }
        )
        seen_complete = False
        for _ in range(5):
            message = ws.receive_json()
            if message["type"] == "chat_complete":
                seen_complete = True
                break
        assert seen_complete
        assert app.state.fake_llm.chat_languages[-1] == "bilingual"
        assert app.state.fake_llm.chat_thinking[-1] is True
        context = app.state.fake_llm.chat_contexts[-1]
        assert "解释一下" in context
        assert context.startswith("user: 解释一下")

        ws.send_json({"type": "stop_listening", "data": {}})
        stopped = ws.receive_json()
        assert stopped["type"] == "status"


def test_force_answer_skips_question_detection(app):
    client = TestClient(app)
    course = client.post("/api/courses", json={"name": "数学"}).json()
    settings = client.patch("/api/settings", json={"auto_answer_language": "bilingual"})
    assert settings.status_code == 200
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "start_listening",
                "data": {"course_id": course["id"], "auto_stop_seconds": 0},
            }
        )
        assert ws.receive_json()["type"] == "status"
        app.state.fake_llm.detect_calls = 0

        ws.send_json({"type": "force_answer", "data": {}})
        seen_question = False
        seen_answer = False
        for _ in range(8):
            message = ws.receive_json()
            if message["type"] == "question_detected":
                seen_question = True
                assert message["data"]["question_text"] == "请根据当前课堂内容生成参考答案"
                assert message["data"]["confidence"] == 1.0
            if message["type"] == "answer_complete":
                seen_answer = True
                break
        assert seen_question
        assert seen_answer
        assert app.state.fake_llm.detect_calls == 0
        assert app.state.fake_llm.answer_languages[-1] == "bilingual"
        assert app.state.fake_llm.answer_models[-1] == "qwen3.5-flash"
        assert app.state.fake_llm.answer_thinking[-1] is False


def test_file_audio_uses_same_manual_turn_detection_as_microphone(app):
    app.state.config.debug_audio_file = True
    client = TestClient(app)
    course = client.post("/api/courses", json={"name": "调试"}).json()
    settings = client.patch(
        "/api/settings",
        json={"audio_source": "file", "audio_file_path": str(app.state.config.data_dir / "demo.mp3")},
    )
    assert settings.status_code == 200
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "start_listening",
                "data": {"course_id": course["id"], "auto_stop_seconds": 0},
            }
        )
        assert ws.receive_json()["type"] == "status"
        assert app.state.fake_asr.manual_turn_detection is True


def test_paragraph_context_keeps_whole_recent_segments():
    paragraphs = ["第一段" * 120, "第二段", "第三段"]

    context = _paragraph_context(paragraphs, 20)

    assert context == "第二段\n第三段"


async def test_segment_guard_waits_for_silence_and_stable_sentence(app):
    await app.state.settings_service.update(
            {
                "audio_source": "microphone",
                "vad_max_segment_seconds": 60,
                "vad_silence_duration_ms": 800,
            }
        )
    course = await _create_course(app, "文件调试")

    await app.state.session_service.start_listening(course_id=course.id)
    await asyncio.sleep(0.2)
    assert app.state.fake_asr.force_commit_count == 0

    speech = (1000).to_bytes(2, byteorder="little", signed=True) * 1600
    silence = b"\x00\x00" * 1600
    pipeline = app.state.session_service._pipeline
    assert pipeline is not None
    for _ in range(120):
        assert pipeline._should_commit_segment_at_audio_boundary(speech) is False
    assert pipeline._should_commit_segment_at_audio_boundary(speech) is False
    for _ in range(7):
        assert pipeline._should_commit_segment_at_audio_boundary(silence) is False
    pipeline._latest_interim_text = "这是一个已经稳定下来的完整课堂句子，适合作为当前转写段落的结束点。"
    pipeline._latest_interim_updated_monotonic = time.monotonic() - 1
    assert pipeline._should_commit_segment_at_audio_boundary(silence) is True


async def test_file_audio_uses_same_segment_guard_as_microphone(app):
    app.state.config.debug_audio_file = True
    await app.state.settings_service.update(
        {
            "audio_source": "file",
            "audio_file_path": str(app.state.config.data_dir / "demo.mp3"),
            "vad_max_segment_seconds": 60,
            "vad_silence_duration_ms": 800,
        }
    )
    course = await _create_course(app, "文件调试")

    await app.state.session_service.start_listening(course_id=course.id)

    pipeline = app.state.session_service._pipeline
    assert pipeline is not None
    speech = (1000).to_bytes(2, byteorder="little", signed=True) * 1600
    silence = b"\x00\x00" * 1600
    for _ in range(120):
        assert pipeline._should_commit_segment_at_audio_boundary(speech) is False
    for _ in range(7):
        assert pipeline._should_commit_segment_at_audio_boundary(silence) is False
    pipeline._latest_interim_text = "这是一个已经稳定下来的完整课堂句子，适合作为当前转写段落的结束点。"
    pipeline._latest_interim_updated_monotonic = time.monotonic() - 1
    assert pipeline._should_commit_segment_at_audio_boundary(silence) is True


async def test_final_transcript_updates_asr_context(app):
    course = await app.state.session_service.start_listening(
        course_id=(await _create_course(app, "上下文")).id,
    )
    await app.state.fake_asr.push("第一段课堂内容。")

    for _ in range(20):
        if app.state.fake_asr.context_updates:
            break
        await asyncio.sleep(0.05)

    assert course.id
    assert app.state.fake_asr.context_updates[-1] == "第一段课堂内容。"


async def test_interim_transcript_can_trigger_question_detection(app):
    await app.state.settings_service.update({"question_cooldown_seconds": 0})
    course = await app.state.session_service.start_listening(
        course_id=(await _create_course(app, "临时检测")).id,
    )
    app.state.fake_llm.detect_calls = 0
    await app.state.fake_asr.push(
        "这里老师正在问一个比较长的问题，为什么机械能守恒需要满足这些条件？",
        is_final=False,
    )

    for _ in range(30):
        if app.state.fake_llm.detect_calls:
            break
        await asyncio.sleep(0.05)

    assert course.id
    assert app.state.fake_llm.detect_calls > 0


async def test_incomplete_final_transcript_merges_with_next_segment(app):
    course = await app.state.session_service.start_listening(
        course_id=(await _create_course(app, "合并")).id,
    )
    await app.state.fake_asr.push("马耳他公民")
    await app.state.fake_asr.push("完成当地大学开发的AI培训课程后。")

    for _ in range(20):
        if app.state.fake_asr.context_updates and "完成当地" in app.state.fake_asr.context_updates[-1]:
            break
        await asyncio.sleep(0.05)

    from class_copilot.infrastructure.persistence.repositories import TranscriptionRepository

    async with app.state.sessionmaker() as db:
        context = await TranscriptionRepository(db).recent_text(course.id)

    assert context == "马耳他公民完成当地大学开发的AI培训课程后。"


async def test_no_output_timeout_stops_session_and_broadcasts_error(app):
    events: list[dict] = []
    app.state.session_service.broadcast = _collect(events)
    await app.state.settings_service.update({"transcript_no_output_timeout_minutes": 0.001})
    course = await _create_course(app, "no output timeout")

    await app.state.session_service.start_listening(course_id=course.id)

    for _ in range(40):
        if any(event["type"] == "error" for event in events):
            break
        await asyncio.sleep(0.05)

    errors = [event for event in events if event["type"] == "error"]
    assert errors
    assert errors[-1]["data"]["code"] == "transcript_no_output_timeout"

    for _ in range(40):
        if not app.state.session_service.state.is_listening:
            break
        await asyncio.sleep(0.05)
    assert app.state.session_service.state.is_listening is False


async def _create_course(app, name: str):
    from class_copilot.infrastructure.persistence.repositories import CourseRepository

    async with app.state.sessionmaker() as db:
        return await CourseRepository(db).create(name)


def _collect(events: list[dict]):
    async def broadcast(event: dict) -> None:
        events.append(event)

    return broadcast
