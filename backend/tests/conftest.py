import asyncio
import io
import time
import wave
from uuid import uuid4

import pytest
from class_copilot.main import create_app
from fastapi.testclient import TestClient

from class_copilot.domain import Fault


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.delay = 0
        self.fail = False
        self.partial_fail = False
        self.text = "这是课堂内容：为什么矩阵乘法不满足交换律？"

    async def stream(self, settings, secret, model, messages, thinking=False, audio=None, structured=False):
        self.calls.append(dict(model=model, messages=messages, thinking=thinking, audio=bool(audio)))
        if self.fail:
            raise Fault("provider_auth", "测试鉴权失败", 503)
        if structured:
            content = '{"questions":[{"text":"为什么矩阵乘法不满足交换律？","confidence":0.95}]}'
        elif audio:
            content = self.text
        else:
            content = "参考回答：矩阵表示线性映射。\n\n复习建议：比较 AB 与 BA。"
        for index in range(0, len(content), 8):
            await asyncio.sleep(self.delay or 0.001)
            yield {"text": content[index : index + 8]}
            if self.partial_fail:
                raise Fault("provider_network", "测试中断", 503, True)
        yield {"actual_model": model, "usage": {"total_tokens": 20}}


class FakeStream:
    def __init__(self, hardware):
        self.hardware = hardware

    async def read(self):
        await asyncio.sleep(0.005)
        return b"\x10\x20" * 1600

    async def close(self):
        self.hardware.closed += 1


class FakeHardware:
    def __init__(self):
        self.opened = 0
        self.closed = 0

    def devices(self, kind):
        return {
            "devices": [
                {"id": kind + ":test", "label": kind + " test device", "kind": kind, "is_default": True}
            ],
            "unavailable_reason": None,
        }

    def resolve(self, kind, device_id):
        if device_id != kind + ":test":
            raise Fault("audio_unavailable", "设备已消失", 503)
        return self.devices(kind)["devices"][0]

    async def open(self, kind, device_id):
        self.resolve(kind, device_id)
        self.opened += 1
        return FakeStream(self)


class Harness:
    def __init__(self, client, app, provider, hardware):
        self.c, self.app, self.provider, self.hardware = client, app, provider, hardware
        self.csrf = self.get("/bootstrap")["csrf_token"]

    def get(self, path):
        response = self.c.get("/api/v1" + path)
        assert response.status_code == 200, response.text
        return response.json()["data"]

    def write(self, path, body=None, method="POST", revision=None, key=None, expected=None):
        headers = {"X-CSRF-Token": self.csrf, "Idempotency-Key": key or str(uuid4())}
        if revision is not None:
            headers["If-Match"] = f'"{revision}"'
        response = self.c.request(
            method, "/api/v1" + path, headers=headers, json={} if body is None else body
        )
        if expected:
            assert response.status_code == expected, response.text
        return response

    def configured(self):
        self.write(
            "/settings",
            {
                "provider": {
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "region": "cn-beijing",
                },
                "detection": {"cooldown_seconds": 0, "dedup_window_seconds": 0},
            },
            "PATCH",
            1,
            expected=200,
        )
        self.write(
            "/providers/dashscope/credential", {"api_key": "secret-for-tests-only"}, "PUT", 1, expected=200
        )

    def lesson(self, mode="auto_answer", name="数学"):
        course = self.write("/courses", {"name": name}, expected=201).json()["data"]
        return self.write(
            "/lessons", {"course_id": course["id"], "automation_mode": mode}, expected=201
        ).json()["data"]

    def wait(self, job, timeout=10):
        identity = job if isinstance(job, str) else job["id"]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = self.get("/jobs/" + identity)
            if current["state"] not in ("queued", "running", "cancelling"):
                return current
            time.sleep(0.02)
        raise AssertionError(f"Job timeout {current}")

    def settle(self, lesson_id, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            jobs = self.get("/jobs?lesson_id=" + lesson_id)["items"]
            if all(j["state"] not in ("queued", "running", "cancelling") for j in jobs):
                return jobs
            time.sleep(0.03)
        raise AssertionError(f"Unsettled jobs: {jobs}")

    def upload(self, lesson_id, seconds=0.5, name="sample.wav", data=None, key=None):
        return self.c.post(
            f"/api/v1/lessons/{lesson_id}/uploads",
            files={"file": (name, data or wav_bytes(seconds), "audio/wav")},
            headers={"X-CSRF-Token": self.csrf, "Idempotency-Key": key or str(uuid4())},
        )

    def analyzed(self, lesson, summary=False):
        response = self.upload(lesson["id"])
        assert response.status_code == 201, response.text
        source = response.json()["data"]
        job = self.write(
            "/sources/" + source["id"] + "/analysis", {"generate_summary": summary}, expected=202
        ).json()["data"]["job"]
        assert self.wait(job)["state"] == "succeeded"
        self.settle(lesson["id"])
        return source


def wav_bytes(seconds=0.5):
    output = io.BytesIO()
    with wave.open(output, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b"\x10\x20" * int(seconds * 16000))
    return output.getvalue()


@pytest.fixture
def h(tmp_path):
    provider, hardware = FakeProvider(), FakeHardware()
    app = create_app(tmp_path / "next", provider=provider, hardware=hardware, testing=True)
    with TestClient(app) as client:
        yield Harness(client, app, provider, hardware)
