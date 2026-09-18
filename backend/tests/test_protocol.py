import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from class_copilot.persistence import events
from class_copilot.provider import Provider

from class_copilot.domain import Fault, Settings


@pytest.mark.asyncio
async def test_snapshot_cursor_replays_commits_and_invalid_epoch_resets(h):
    initial = h.get("/bootstrap")["event_cursor"]
    h.lesson()
    route = next(r for r in h.app.routes if getattr(r, "path", "") == "/api/v1/events")

    async def connected():
        return False

    request = SimpleNamespace(headers={}, is_disconnected=connected)
    response = await route.endpoint(request, after=initial)
    first = await anext(response.body_iterator)
    assert "event: entity.updated" in first and "course.created" in first
    payload = json.loads(first.split("data: ")[1])
    assert payload["data"]["name"] == "数学"
    assert payload["cursor"].split(":")[0] == initial.split(":")[0]
    await response.body_iterator.aclose()
    response = await route.endpoint(request, after=str(uuid4()) + ":0")
    assert "reset_required" in await anext(response.body_iterator)
    await response.body_iterator.aclose()
    water = h.get("/bootstrap")["event_cursor"]
    with h.app.state.db.tx() as tx:
        tx.conn.execute(events.delete())
    assert h.get("/bootstrap")["event_cursor"] == water
    response = await route.endpoint(request, after=initial)
    assert "reset_required" in await anext(response.body_iterator)
    await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_provider_payload_no_tools_and_midstream_failure_never_retries(monkeypatch):
    calls = []
    content = 'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n'

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, text=content)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    settings = Settings().model_dump()
    settings["provider"]["base_url"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    chunks = []
    with pytest.raises(Fault) as error:
        async for chunk in Provider().stream(
            settings,
            "secret",
            "qwen3.8-omni-flash",
            [{"role": "user", "content": "transcribe"}],
            audio=b"wave",
        ):
            chunks.append(chunk)
    assert error.value.code == "provider_disconnected"
    assert len(calls) == 1
    assert calls[0]["model"] == "qwen3.8-omni-flash"
    assert calls[0]["reasoning_effort"] == "none"
    assert "tools" not in calls[0]
    assert calls[0]["messages"][0]["content"][1]["input_audio"]["data"].startswith("data:audio/wav;base64,")
    assert chunks[0]["text"] == "partial"


def test_upload_key_replay_and_five_decodable_formats(h, tmp_path):
    from class_copilot.audio import run_media
    from conftest import wav_bytes

    lesson = h.lesson("transcribe_only")
    key = str(uuid4())
    first = h.upload(lesson["id"], key=key)
    replay = h.upload(lesson["id"], key=key)
    assert replay.status_code == 201 and replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["data"]["id"] == first.json()["data"]["id"]
    raw = tmp_path / "sample.wav"
    raw.write_bytes(wav_bytes(1))
    for ext in ("mp3", "m4a", "flac", "ogg"):
        converted = tmp_path / ("sample." + ext)
        run_media(["ffmpeg", "-v", "error", "-y", "-i", str(raw), str(converted)])
        response = h.upload(lesson["id"], name=converted.name, data=converted.read_bytes())
        assert response.status_code == 201, response.text
    assert h.get("/lessons/" + lesson["id"] + "/sources")["total"] == 5


def test_summary_auto_waits_for_answers_and_reports_partial_transcription(h):
    h.configured()
    lesson = h.lesson("auto_answer")
    source = h.upload(lesson["id"], seconds=25).json()["data"]
    original = h.provider.stream
    count = 0

    async def fail_second(*args, **kwargs):
        nonlocal count
        if kwargs.get("audio"):
            count += 1
            if count == 2:
                raise Fault("provider_auth", "测试区间失败", 503)
        async for chunk in original(*args, **kwargs):
            yield chunk

    h.provider.stream = fail_second
    result = h.write("/sources/" + source["id"] + "/analysis", {}, expected=202).json()["data"]
    assert h.wait(result["job"])["state"] == "failed"
    import time

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        summaries = h.get("/lessons/" + lesson["id"] + "/summaries")["items"]
        if summaries and summaries[-1]["state"] == "completed":
            break
        time.sleep(0.03)
    assert summaries and summaries[0]["state"] == "completed"
    assert summaries[0]["context_coverage"]["gaps"]
    assert summaries[0]["context_coverage"]["answer_version_ids"]
