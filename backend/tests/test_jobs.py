import concurrent.futures
import time

from class_copilot.dto import ChatTurn, Question, Summary


def test_post_class_chat_partial_failure_retry_versions_and_export(h):
    h.configured()
    lesson = h.lesson("transcribe_only")
    h.analyzed(lesson)
    h.provider.partial_fail = True
    result = h.write(
        "/lessons/" + lesson["id"] + "/chat-turns", {"content": "解释一下矩阵"}, expected=202
    ).json()["data"]
    assert h.wait(result["job"])["state"] == "failed"
    turn_id = result["resource"]["id"]
    turn = h.get("/chat-turns/" + turn_id)
    assert turn["replies"][0]["content"]
    assert turn["replies"][0]["state"] == "failed"
    h.provider.partial_fail = False
    retried = h.write("/jobs/" + result["job"]["id"] + "/retry", {}, expected=202).json()["data"]
    assert h.wait(retried["job"])["state"] == "succeeded"
    turn = h.get("/chat-turns/" + turn_id)
    ChatTurn.model_validate(turn)
    assert len(turn["replies"]) == 2
    assert h.get("/lessons/" + lesson["id"] + "/chat-turns")["total"] == 1
    assert turn["selected_reply_id"] == turn["replies"][1]["id"]
    export = h.c.get("/api/v1/lessons/" + lesson["id"] + "/export").text
    assert "failed" in export and "completed" in export and "解释一下矩阵" in export


def test_concurrent_chat_busy_cancel_and_delete_guard(h):
    h.configured()
    lesson = h.lesson()
    h.provider.delay = 0.2
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda i: h.write("/lessons/" + lesson["id"] + "/chat-turns", {"content": str(i)}), range(2)
            )
        )
    assert sorted(r.status_code for r in responses) == [202, 409]
    job = next(r.json()["data"]["job"] for r in responses if r.status_code == 202)
    h.write("/lessons/" + lesson["id"], method="DELETE", expected=409)
    h.write("/providers/dashscope/credential", method="DELETE", expected=409)
    time.sleep(0.3)
    h.write("/jobs/" + job["id"] + "/cancel", {})
    assert h.wait(job)["state"] == "cancelled"
    turns = h.get("/lessons/" + lesson["id"] + "/chat-turns")["items"]
    assert len(turns) == 1
    assert turns[0]["replies"][0]["content"]
    delete = h.write("/lessons/" + lesson["id"], method="DELETE", expected=202).json()["data"]["job"]
    assert h.wait(delete)["state"] == "succeeded"
    assert h.c.get("/api/v1/lessons/" + lesson["id"]).status_code == 404
    assert h.get("/courses")["items"][0]["lesson_count"] == 0


def test_manual_detection_direct_answer_versions_and_summary_staleness(h):
    h.configured()
    lesson = h.lesson("transcribe_only")
    h.analyzed(lesson)
    segment = h.get("/lessons/" + lesson["id"] + "/transcripts")["items"][0]
    direct = h.write(
        "/lessons/" + lesson["id"] + "/direct-answers",
        {"segment_ids": [segment["id"]], "style": "detailed"},
        expected=202,
    ).json()["data"]
    assert h.wait(direct["job"])["state"] == "succeeded"
    assert not any(c for c in h.provider.calls if "Find genuine classroom" in str(c["messages"]))
    question = h.get("/questions/" + direct["resource"]["id"])
    Question.model_validate(question)
    result = h.write(
        "/questions/" + question["id"] + "/answers", {"style": "brief", "language": "en"}, expected=202
    ).json()["data"]
    assert h.wait(result["job"])["state"] == "succeeded"
    assert len(h.get("/questions/" + question["id"])["answer_versions"]) == 2
    result = h.write("/lessons/" + lesson["id"] + "/summaries", {}, expected=202).json()["data"]
    assert h.wait(result["job"])["state"] == "succeeded"
    summary = h.get("/summaries/" + result["resource"]["id"])
    Summary.model_validate(summary)
    assert summary["is_stale"] is False
    chat = h.write("/lessons/" + lesson["id"] + "/chat-turns", {"content": "hello"}, expected=202).json()[
        "data"
    ]
    h.wait(chat["job"])
    assert h.get("/summaries/" + summary["id"])["is_stale"] is False
    detect = h.write(
        "/lessons/" + lesson["id"] + "/question-detections", {"segment_ids": [segment["id"]]}, expected=202
    ).json()["data"]
    h.wait(detect["job"])
    assert h.get("/summaries/" + summary["id"])["is_stale"] is True


def test_audio_exclusivity_stop_tail_and_chat_independence(h):
    h.configured()
    lesson = h.lesson("transcribe_only")
    first = h.write(
        "/lessons/" + lesson["id"] + "/recordings",
        {"kind": "microphone", "device_id": "microphone:test"},
        expected=202,
    ).json()["data"]
    h.write(
        "/lessons/" + lesson["id"] + "/recordings",
        {"kind": "microphone", "device_id": "microphone:test"},
        expected=409,
    )
    source_id = first["resource"]["id"]
    deadline = time.monotonic() + 5
    while h.get("/sources/" + source_id)["capture_state"] == "preparing" and time.monotonic() < deadline:
        time.sleep(0.02)
    h.provider.delay = 0.15
    chat = h.write(
        "/lessons/" + lesson["id"] + "/chat-turns", {"content": "keep talking"}, expected=202
    ).json()["data"]
    time.sleep(0.12)
    start = time.monotonic()
    stop = h.write("/sources/" + source_id + "/stop", {}, expected=202).json()["data"]
    assert time.monotonic() - start < 0.5
    assert h.wait(stop["job"])["state"] == "succeeded"
    assert h.hardware.closed == 1
    assert h.wait(chat["job"])["state"] == "succeeded"
    h.settle(lesson["id"])
    source = h.get("/sources/" + source_id)
    assert source["duration_ms"] > 0
    assert source["capture_state"] == "ready"
    assert source["transcription_state"] == "completed"
    assert h.get("/lessons/" + lesson["id"] + "/transcripts")["total"] > 0
    assert h.get("/bootstrap")["active_audio"] is None
    assert h.write("/sources/" + source_id + "/stop", {}, expected=200)


def test_cancel_analysis_resume_only_missing_chunks(h):
    h.configured()
    lesson = h.lesson("transcribe_only")
    source = h.upload(lesson["id"], seconds=25).json()["data"]
    h.provider.delay = 0.05
    result = h.write(
        "/sources/" + source["id"] + "/analysis", {"generate_summary": False}, expected=202
    ).json()["data"]
    deadline = time.monotonic() + 5
    while h.get("/lessons/" + lesson["id"] + "/transcripts")["total"] < 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    h.write("/jobs/" + result["job"]["id"] + "/cancel", {})
    assert h.wait(result["job"])["state"] == "cancelled"
    old_segments = h.get("/lessons/" + lesson["id"] + "/transcripts")["items"]
    h.provider.delay = 0
    retried = h.write("/jobs/" + result["job"]["id"] + "/retry", {}, expected=202).json()["data"]
    assert h.wait(retried["job"])["state"] == "succeeded"
    segments = h.get("/lessons/" + lesson["id"] + "/transcripts")["items"]
    assert len(segments) == 3
    assert set(s["id"] for s in old_segments).issubset(s["id"] for s in segments)
    assert len({s["ordinal"] for s in segments}) == 3


def test_upload_before_configuration_uses_first_analysis_snapshot(h):
    lesson = h.lesson("transcribe_only")
    source = h.upload(lesson["id"]).json()["data"]
    h.configured()
    response = h.write(
        "/sources/" + source["id"] + "/analysis", {"generate_summary": False}, expected=202
    ).json()["data"]
    with h.app.state.db.tx() as tx:
        snapshot = tx.get("jobs", response["job"]["id"])["snapshot"]
    assert snapshot["settings"]["provider"]["base_url"].startswith("https://dashscope.")
    assert h.wait(response["job"])["state"] == "succeeded"


def test_long_summary_covers_large_single_segment_with_bounded_requests(h):
    h.configured()
    lesson = h.lesson("transcribe_only")
    h.analyzed(lesson)
    with h.app.state.db.tx() as tx:
        segment = tx.all("transcript_segments", lesson_id=lesson["id"])[0]
        segment["text"] = "BEGIN_EVIDENCE " + "课堂内容" * 12000 + " END_EVIDENCE"
        tx.save("transcript_segments", segment)
        h.app.state.service.bump(tx, lesson["id"])
    h.provider.calls.clear()
    result = h.write("/lessons/" + lesson["id"] + "/summaries", {}, expected=202).json()["data"]
    assert h.wait(result["job"])["state"] == "succeeded"
    calls = h.provider.calls
    assert len(calls) > 2
    combined = str([c["messages"] for c in calls])
    assert "BEGIN_EVIDENCE" in combined and "END_EVIDENCE" in combined
    assert all(sum(len(m["content"].encode()) + 16 for m in c["messages"]) <= 32000 for c in calls)
    summary = h.get("/summaries/" + result["resource"]["id"])
    assert summary["context_coverage"]["truncated"] is False


def test_question_cooldown_is_isolated_by_lesson(h):
    h.configured()
    settings = h.get("/settings")
    h.write(
        "/settings",
        {"detection": {"cooldown_seconds": 120, "dedup_window_seconds": 300}},
        "PATCH",
        settings["revision"],
        expected=200,
    )
    first = h.lesson(name="课程一")
    second = h.lesson(name="课程二")
    h.analyzed(first)
    h.analyzed(second)
    assert h.get("/lessons/" + first["id"] + "/questions")["total"] == 1
    assert h.get("/lessons/" + second["id"] + "/questions")["total"] == 1


def test_stalled_stream_checkpoints_small_partial_text_within_one_second(h):
    import asyncio
    import time

    h.configured()
    lesson = h.lesson()

    async def stalled(*args, **kwargs):
        yield {"text": "一个已收到但模型随后暂停的片段"}
        await asyncio.sleep(30)

    h.provider.stream = stalled
    result = h.write(
        "/lessons/" + lesson["id"] + "/chat-turns", {"content": "测试检查点"}, expected=202
    ).json()["data"]
    deadline = time.monotonic() + 2
    reply = {}
    while time.monotonic() < deadline:
        reply = h.get("/chat-turns/" + result["resource"]["id"])["replies"][0]
        if reply["content"]:
            break
        time.sleep(0.03)
    assert reply["content"] and reply["state"] == "streaming"
    h.write("/jobs/" + result["job"]["id"] + "/cancel", {})
    assert h.wait(result["job"])["state"] == "cancelled"
