"""Bailian Chat Completions adapter. No model substitution, no tool execution."""

import asyncio
import base64
import json
import random

import httpx

from .domain import Fault

CAPABILITIES = {
    "qwen3.8-omni-flash": dict(audio=True, thinking=True, structured=True),
    "qwen3.8-flash": dict(audio=False, thinking=True, structured=True),
    "qwen3.8-max": dict(audio=False, thinking=True, structured=True),
}


class Provider:
    async def stream(self, settings, secret, model, messages, thinking=False, audio=None, structured=False):
        caps = CAPABILITIES.get(model)
        if not caps or (audio and not caps["audio"]) or (thinking and not caps["thinking"]):
            raise Fault("model_capability_unsupported", "模型不支持所选能力", 422)
        payload = dict(
            model=model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            max_tokens=8192,
            reasoning_effort="medium" if thinking else "none",
        )
        if audio:
            encoded = base64.b64encode(audio).decode()
            payload["messages"] = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": messages[-1]["content"]},
                        {
                            "type": "input_audio",
                            "input_audio": {"data": f"data:audio/wav;base64,{encoded}", "format": "wav"},
                        },
                    ],
                }
            ]
        if structured:
            payload["response_format"] = {"type": "json_object"}
        emitted = False
        for attempt in range(3):
            delay = min(2**attempt + random.random(), 10)
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(60, connect=10), follow_redirects=False
                ) as client:
                    async with client.stream(
                        "POST",
                        settings["provider"]["base_url"] + "/chat/completions",
                        headers={"Authorization": f"Bearer {secret}"},
                        json=payload,
                    ) as response:
                        if response.status_code >= 400:
                            status = response.status_code
                            retryable = status == 429 or status >= 500
                            try:
                                delay = max(0, float(response.headers.get("Retry-After", delay)))
                            except ValueError:
                                pass
                            code = (
                                "provider_auth"
                                if status in (401, 403)
                                else "provider_rate_limit"
                                if status == 429
                                else "provider_error"
                            )
                            raise Fault(code, "模型服务拒绝请求，请检查区域、模型权限和凭据", 503, retryable)
                        finished = False
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            raw = line[5:].strip()
                            if raw == "[DONE]":
                                finished = True
                                break
                            try:
                                chunk = json.loads(raw)
                            except ValueError:
                                raise Fault("provider_protocol", "模型流格式无效", 503) from None
                            if chunk.get("error"):
                                raise Fault("provider_error", "模型流返回错误", 503)
                            choices = chunk.get("choices") or []
                            if choices:
                                choice = choices[0]
                                reason = choice.get("finish_reason")
                                if reason and reason != "stop":
                                    raise Fault(
                                        "provider_incomplete", "模型输出未完整结束，请重试或缩短输入", 503
                                    )
                                if reason == "stop":
                                    finished = True
                                content = choice.get("delta", {}).get("content")
                                if content:
                                    emitted = True
                                    yield {"text": content}
                            if chunk.get("usage") or chunk.get("model"):
                                yield {"usage": chunk.get("usage"), "actual_model": chunk.get("model")}
                        if not finished:
                            raise Fault("provider_disconnected", "模型连接提前结束", 503, True)
                        return
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                error = Fault(
                    "provider_timeout" if isinstance(exc, httpx.TimeoutException) else "provider_network",
                    "模型服务连接超时或中断",
                    503,
                    True,
                )
            except Fault as exc:
                error = exc
            if emitted or not error.retryable or attempt == 2 or delay > 20:
                raise error
            await asyncio.sleep(max(0, delay))
