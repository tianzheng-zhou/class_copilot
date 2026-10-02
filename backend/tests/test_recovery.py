import asyncio
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from class_copilot import audio, context
from class_copilot.domain import Fault
from class_copilot.main import create_app
from class_copilot.persistence import Database
from class_copilot.service import Service
from conftest import FakeHardware, FakeProvider, Harness
from fastapi.testclient import TestClient


def test_model_failure_does_not_stop_audio_and_stop_releases_slot(h):
    h.configured()
    lesson = h.lesson("transcribe_only")
    h.provider.fail = True
    response = h.write(
        "/lessons/" + lesson["id"] + "/recordings",
        {"kind": "microphone", "device_id": "microphone:test"},
        expected=202,
    ).json()["data"]
    source_id = response["resource"]["id"]
    deadline = time.monotonic() + 5
    while h.get("/sources/" + source_id)["transcription_state"] != "failed" and time.monotonic() < deadline:
        time.sleep(0.03)
    assert h.get("/sources/" + source_id)["capture_state"] == "capturing"
    assert h.get("/bootstrap")["active_audio"] is not None
    stop = h.write("/sources/" + source_id + "/stop", {}, expected=202).json()["data"]
    assert h.wait(stop["job"])["state"] == "succeeded"
    assert h.hardware.closed == 1
    assert h.get("/sources/" + source_id)["assets"]
    assert h.get("/bootstrap")["active_audio"] is None


def test_stop_during_slow_device_open_does_not_restart_recording(h):
    h.configured()
    lesson = h.lesson("transcribe_only")
    original_open = h.hardware.open

    async def slow_open(kind, identity):
        await asyncio.sleep(0.2)
        return await original_open(kind, identity)

    h.hardware.open = slow_open
    response = h.write(
        "/lessons/" + lesson["id"] + "/recordings",
        {"kind": "microphone", "device_id": "microphone:test"},
        expected=202,
    ).json()["data"]
    time.sleep(0.12)
    stop = h.write("/sources/" + response["resource"]["id"] + "/stop", {}, expected=202).json()["data"]
    assert h.wait(stop["job"])["state"] == "succeeded"
    h.settle(lesson["id"])
    assert h.hardware.opened == h.hardware.closed
    assert h.get("/sources/" + response["resource"]["id"])["capture_state"] == "ready"


def test_auto_stop_is_from_original_start_and_releases_capture(h):
    h.configured()
    lesson = h.lesson("transcribe_only")
    response = h.write(
        "/lessons/" + lesson["id"] + "/recordings",
        {"kind": "microphone", "device_id": "microphone:test"},
        expected=202,
    ).json()["data"]
    source_id = response["resource"]["id"]
    h.wait(response["job"])

    def backdate():
        with h.app.state.db.tx() as tx:
            source = tx.get("audio_sources", source_id)
            source["started_at"] = (
                (datetime.now(UTC) - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
            )
            return tx.save("audio_sources", source)

    source = backdate()
    h.write("/sources/" + source_id, {"auto_stop_minutes": 1}, "PATCH", source["revision"], expected=200)
    h.settle(lesson["id"])
    assert h.get("/sources/" + source_id)["capture_state"] == "ready"
    assert h.hardware.closed == 1


def test_mode_change_cancels_queued_automation_and_running_detection_cannot_answer(h):
    h.configured()
    lesson = h.lesson("transcribe_only")
    h.analyzed(lesson)
    segment = h.get("/lessons/" + lesson["id"] + "/transcripts")["items"][0]
    current = h.get("/lessons/" + lesson["id"])
    h.write(
        "/lessons/" + lesson["id"] + "/automation",
        {"mode": "auto_answer"},
        "PUT",
        current["revision"],
        expected=200,
    )
    h.provider.delay = 0.1
    with h.app.state.db.tx() as tx:
        running = h.app.state.service.detect(tx, lesson["id"], [segment], True)
        queued = h.app.state.service.detect(tx, lesson["id"], [segment], True)
    deadline = time.monotonic() + 4
    while h.get("/jobs/" + running["id"])["state"] == "queued" and time.monotonic() < deadline:
        time.sleep(0.02)
    current = h.get("/lessons/" + lesson["id"])
    h.write(
        "/lessons/" + lesson["id"] + "/automation",
        {"mode": "detect_only"},
        "PUT",
        current["revision"],
        expected=200,
    )
    assert h.wait(queued)["state"] == "cancelled"
    assert h.wait(running)["state"] == "succeeded"
    questions = h.get("/lessons/" + lesson["id"] + "/questions")["items"]
    assert questions and not questions[0]["answer_versions"]


def test_restart_interrupts_paid_tasks_recovers_audio_and_never_opens_device(tmp_path):
    root = tmp_path / "next"
    db = Database(root)
    service = Service(db)
    with db.tx() as tx:
        course = tx.save("courses", {"id": str(uuid4()), "name": "恢复", "normalized_name": "恢复"}, True)
        lesson = tx.save(
            "lessons",
            {
                "id": str(uuid4()),
                "course_id": course["id"],
                "custom_title": None,
                "lifecycle": "ready",
                "automation_mode": "transcribe_only",
                "automation_revision": 1,
                "content_revision": 0,
            },
            True,
        )
        source = service.new_source(tx, lesson["id"], "microphone", capture_state="capturing")
        service.job(
            tx,
            "transcribe_source",
            lesson["id"],
            source["id"],
            snapshot={"generate_summary": True},
            slot="audio",
        )
    directory = db.path(f"lessons/{lesson['id']}/{source['id']}/chunks")
    audio.save_chunk(directory, 1, 0, b"\x01\x10" * 8000)
    db.close()
    hardware, provider = FakeHardware(), FakeProvider()
    with TestClient(create_app(root, provider, hardware, testing=True)) as client:
        h = Harness(client, client.app, provider, hardware)
        h.settle(lesson["id"])
        recovered = h.get("/sources/" + source["id"])
        assert recovered["capture_state"] == "interrupted"
        assert recovered["duration_ms"] == 500
        assert recovered["assets"][0]["state"] == "partial"
        assert recovered["gap_ranges"][0]["reason"] == "possible_unflushed_audio"
        assert not hardware.opened and not provider.calls
        assert any(j["state"] == "interrupted" for j in h.get("/jobs")["items"])


def test_process_lock_and_legacy_directory_rejection(tmp_path):
    root = tmp_path / "new"
    db = Database(root)
    with pytest.raises(RuntimeError, match="already in use"):
        Database(root)
    db.close()
    legacy = tmp_path / "old"
    legacy.mkdir()
    marker = legacy / "class_copilot.db"
    marker.write_bytes(b"untouched legacy data")
    with pytest.raises(RuntimeError, match="Legacy"):
        Database(legacy)
    assert marker.read_bytes() == b"untouched legacy data"


def test_untrusted_context_budget_keeps_current_question_and_no_duplicate_history():
    segments = [
        {
            "id": str(uuid4()),
            "source_id": "s",
            "ordinal": i,
            "start_ms": i * 1000,
            "end_ms": (i + 1) * 1000,
            "text": "课堂材料" * 3000,
        }
        for i in range(15)
    ]
    turns = [
        {
            "id": str(i),
            "user_content": "previous question " + str(i),
            "replies": [{"content": "previous answer", "state": "completed"}],
        }
        for i in range(100)
    ]
    messages, coverage = context.prepare(segments, turns, [], "the current question")
    assert sum(context.cost(m["content"]) for m in messages) <= 32000
    assert messages[-1]["content"] == "the current question"
    assert coverage["truncated"] is True
    assert sum(m["content"] == "previous question 99" for m in messages) == 1
    with pytest.raises(Fault):
        context.prepare([], [], [], "中" * 20000)


def test_failed_file_cleanup_is_retryable_and_keeps_lesson_visible(h, monkeypatch):
    import class_copilot.workers as workers

    h.configured()
    lesson = h.lesson("transcribe_only")
    h.analyzed(lesson)
    original = workers.shutil.rmtree

    def fail(*args, **kwargs):
        raise PermissionError("test")

    monkeypatch.setattr(workers.shutil, "rmtree", fail)
    job = h.write("/lessons/" + lesson["id"], method="DELETE", expected=202).json()["data"]["job"]
    assert h.wait(job)["error"]["code"] == "cleanup_failed"
    assert h.get("/lessons/" + lesson["id"])["lifecycle"] == "deleting"
    h.write("/lessons/" + lesson["id"] + "/chat-turns", {"content": "hello"}, expected=409)
    monkeypatch.setattr(workers.shutil, "rmtree", original)
    retry = h.write("/jobs/" + job["id"] + "/retry", {}, expected=202).json()["data"]["job"]
    assert h.wait(retry)["state"] == "succeeded"


def test_encoding_failure_does_not_leave_transcription_or_audio_slot_stuck(h, monkeypatch):
    h.configured()
    lesson = h.lesson("transcribe_only")
    original = audio.encode_mp3

    def fail(*args):
        raise Fault("audio_encoding_failed", "测试编码失败", 503, True)

    monkeypatch.setattr(audio, "encode_mp3", fail)
    recording = h.write(
        "/lessons/" + lesson["id"] + "/recordings",
        {"kind": "microphone", "device_id": "microphone:test"},
        expected=202,
    ).json()["data"]
    h.wait(recording["job"])
    time.sleep(0.1)
    stop = h.write("/sources/" + recording["resource"]["id"] + "/stop", {}, expected=202).json()["data"]
    assert h.wait(stop["job"])["state"] == "failed"
    h.settle(lesson["id"])
    assert h.get("/bootstrap")["active_audio"] is None
    assert h.get("/sources/" + recording["resource"]["id"])["transcription_state"] == "completed"
    monkeypatch.setattr(audio, "encode_mp3", original)
    retried = h.write("/jobs/" + stop["job"]["id"] + "/retry", {}, expected=202).json()["data"]
    assert h.wait(retried["job"])["state"] == "succeeded"
    assert h.get("/sources/" + recording["resource"]["id"])["assets"]
