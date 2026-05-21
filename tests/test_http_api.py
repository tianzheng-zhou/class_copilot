from __future__ import annotations

from class_copilot.infrastructure.persistence.repositories import SessionRepository


async def test_courses_settings_and_session_export(client, app):
    created = await client.post("/api/courses", json={"name": "线性代数"})
    assert created.status_code == 201
    course = created.json()

    duplicate = await client.post("/api/courses", json={"name": "线性代数"})
    assert duplicate.status_code == 409

    settings = await client.get("/api/settings")
    assert settings.status_code == 200
    assert settings.json()["dashscope_api_key"] == "sk-t****"
    assert settings.json()["dashscope_api_key_set"] is True
    assert settings.json()["transcript_no_output_timeout_minutes"] == 5.0

    patched = await client.patch(
        "/api/settings",
        json={
            "asr_language": "bilingual",
            "auto_answer_language": "en",
            "auto_answer_model": "qwen3.5-plus",
            "chat_language": "zh",
            "transcript_no_output_timeout_minutes": 3.5,
        },
    )
    assert patched.status_code == 200
    assert patched.json()["asr_language"] == "bilingual"
    assert patched.json()["auto_answer_language"] == "en"
    assert patched.json()["auto_answer_model"] == "qwen3.5-plus"
    assert patched.json()["chat_language"] == "zh"
    assert patched.json()["transcript_no_output_timeout_minutes"] == 3.5

    legacy = await client.patch("/api/settings", json={"language": "en"})
    assert legacy.status_code == 200
    assert legacy.json()["language"] == "en"
    assert legacy.json()["asr_language"] == "en"
    assert legacy.json()["auto_answer_language"] == "en"
    assert legacy.json()["chat_language"] == "en"
    assert legacy.json()["debug_audio_file"] is False

    file_source = await client.patch(
        "/api/settings",
        json={"audio_source": "file", "audio_file_path": str(app.state.config.data_dir / "demo.mp3")},
    )
    assert file_source.status_code == 403

    async with app.state.sessionmaker() as db:
        session = await SessionRepository(db).create(
            course_id=course["id"],
            date="2026-05-19",
            recording_path=str(app.state.config.recordings_dir / "test.mp3"),
        )
        await SessionRepository(db).finish(
            session.id,
            status="stopped",
            ended_at=None,
            recording_duration_seconds=1,
            recording_file_size_bytes=8,
        )

    listing = await client.get("/api/sessions")
    assert listing.status_code == 200
    assert listing.json()[0]["course_name"] == "线性代数"

    export = await client.get(f"/api/sessions/{session.id}/export.md")
    assert export.status_code == 200
    assert "线性代数" in export.text


async def test_course_delete_conflict(client):
    course = (await client.post("/api/courses", json={"name": "数学"})).json()
    deleted = await client.delete(f"/api/courses/{course['id']}")
    assert deleted.status_code == 204
