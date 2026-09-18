import concurrent.futures
import json
from uuid import uuid4

import pytest
from class_copilot.dto import Course, Lesson, Source


def test_isolation_validation_and_optimistic_concurrency(h, tmp_path):
    assert h.get("/courses")["items"] == []
    course = h.write("/courses", {"name": "  线性代数  "}, expected=201).json()["data"]
    Course.model_validate(course)
    h.write("/courses", {"name": "线性代数"}, expected=409)
    h.write("/courses", {"name": " "}, expected=422)
    h.write("/courses", {"name": "a", "extra": True}, expected=422)
    h.write("/courses/" + course["id"], {"name": "新名称"}, "PATCH", expected=428)
    h.write("/courses/" + course["id"], {"name": "新名称"}, "PATCH", 8, expected=412)
    renamed = h.write("/courses/" + course["id"], {"name": "新名称"}, "PATCH", 1, expected=200).json()["data"]
    lesson = h.write("/lessons", {"course_id": course["id"]}, expected=201).json()["data"]
    Lesson.model_validate(lesson)
    assert lesson["course_name"] == renamed["name"]
    h.write("/courses/" + course["id"], method="DELETE", expected=409)
    h.write("/lessons/" + lesson["id"], {"custom_title": "第一讲"}, "PATCH", 1, expected=200)
    current = h.get("/lessons/" + lesson["id"])
    h.write("/lessons/" + lesson["id"], {}, "PATCH", current["revision"], expected=200)
    assert h.get("/lessons/" + lesson["id"])["custom_title"] == "第一讲"
    assert h.c.get("/api/v1/lessons/not-uuid").status_code == 422
    assert h.c.post("/api/v1/courses", json={"name": "bad"}).status_code == 403
    assert h.c.get("/api/v1/bootstrap", headers={"Host": "attacker.example"}).status_code == 403
    assert h.c.get("/api/v1/bootstrap", headers={"Origin": "https://attacker.example"}).status_code == 403


def test_idempotency_concurrent_create(h):
    key = str(uuid4())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: h.write("/courses", {"name": "同一请求"}, key=key), range(2)))
    assert [r.status_code for r in results] == [201, 201]
    assert results[0].json()["data"]["id"] == results[1].json()["data"]["id"]
    assert h.get("/courses")["total"] == 1
    assert any(r.headers.get("Idempotent-Replayed") == "true" for r in results)
    h.write("/courses", {"name": "不同请求"}, key=key, expected=409)
    assert h.get("/commands/" + key)["response_status"] == 201


def test_settings_atomic_and_credentials_not_leaked(h):
    before = h.get("/settings")
    h.write(
        "/settings",
        {"generation": {"language": "en"}, "transcription": {"silence_ms": 0}},
        "PATCH",
        before["revision"],
        expected=422,
    )
    assert h.get("/settings") == before
    h.write("/settings", {"models": {"answer": "qwen3.8-max"}}, "PATCH", before["revision"], expected=200)
    current = h.get("/settings")
    assert current["models"]["transcription"] == "qwen3.8-omni-flash"
    assert current["models"]["answer"] == "qwen3.8-max"
    h.write("/settings", {"audio": {"auto_stop_minutes": True}}, "PATCH", current["revision"], expected=422)
    h.write(
        "/settings",
        {"provider": {"base_url": "https://evil.example/compatible-mode/v1"}},
        "PATCH",
        current["revision"],
        expected=422,
    )
    h.write("/providers/dashscope/credential", {"api_key": "top-secret-test-key"}, "PUT", 1, expected=200)
    assert not h.provider.calls
    public = json.dumps([h.get("/settings"), h.get("/providers/dashscope/credential")])
    assert "top-secret-test-key" not in public
    h.write("/providers/dashscope/credential", method="DELETE", expected=204)
    assert not h.get("/providers/dashscope/credential")["set"]


def test_pagination_timezone_and_filter_binding(h):
    for i in range(4):
        h.lesson(name=f"课程 {i}")
    page = h.get("/lessons?limit=2")
    assert len(page["items"]) == 2 and page["total"] == 4
    next_page = h.get("/lessons?limit=2&cursor=" + page["next_cursor"])
    assert len(next_page["items"]) == 2
    assert not set(x["id"] for x in page["items"]) & set(x["id"] for x in next_page["items"])
    assert h.c.get("/api/v1/lessons?q=changed&cursor=" + page["next_cursor"]).status_code == 422
    assert h.c.get("/api/v1/lessons?date_from=2026-09-18").status_code == 422
    assert h.get("/lessons?date_from=2020-01-01&timezone=Asia%2FSingapore")["total"] == 4


@pytest.mark.parametrize(
    "mode,questions,answers", [("auto_answer", 1, 1), ("detect_only", 1, 0), ("transcribe_only", 0, 0)]
)
def test_import_modes_same_pipeline_and_playback(h, mode, questions, answers):
    h.configured()
    lesson = h.lesson(mode)
    source = h.analyzed(lesson)
    snapshot = h.get("/lessons/" + lesson["id"] + "/snapshot")
    assert snapshot["transcripts"]["total"] == 1
    assert snapshot["questions"]["total"] == questions
    if questions:
        assert len(snapshot["questions"]["items"][0]["answer_versions"]) == answers
    saved = h.get("/sources/" + source["id"])
    Source.model_validate(saved)
    playback = next(a for a in saved["assets"] if a["role"] == "playback")
    response = h.c.get(playback["url"], headers={"Range": "bytes=0-99"})
    assert response.status_code == 206 and len(response.content) == 100
    assert h.upload(lesson["id"]).status_code == 409
    h.write("/sources/" + source["id"] + "/analysis", {}, expected=409)


def test_bad_upload_and_no_empty_summary(h):
    lesson = h.lesson()
    assert h.upload(lesson["id"], data=b"invalid audio").status_code == 422
    assert h.upload(lesson["id"], name="bad.txt").status_code == 415
    assert h.get("/lessons/" + lesson["id"] + "/sources")["total"] == 0
    h.configured()
    h.write("/lessons/" + lesson["id"] + "/summaries", {}, expected=422)


def test_explicit_null_is_rejected_except_documented_nullable_fields(h):
    h.configured()
    lesson = h.lesson()
    h.write("/lessons/" + lesson["id"] + "/chat-turns", {"content": "hello", "thinking": None}, expected=422)
    h.write("/lessons/" + lesson["id"] + "/summaries", {"language": None}, expected=422)
    h.write("/lessons/" + lesson["id"], {"custom_title": None}, "PATCH", lesson["revision"], expected=200)


def test_streamed_request_limit_without_content_length(h):
    def chunks():
        yield b'{"name":"'
        for _ in range(20):
            yield b"a" * 65536
        yield b'"}'

    response = h.c.post(
        "/api/v1/courses",
        content=chunks(),
        headers={"Content-Type": "application/json", "X-CSRF-Token": h.csrf, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert h.get("/courses")["total"] == 0
