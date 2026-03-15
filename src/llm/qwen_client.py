"""阿里云百炼 Qwen LLM 客户端（OpenAI 兼容接口）。"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from openai import OpenAI

from src.config.constants import LLM_BASE_URL, LLM_MODEL_FLASH, LLM_MODEL_PLUS

logger = logging.getLogger(__name__)


class QwenClient:
    """Qwen 大模型客户端。"""

    def __init__(self, api_key: str) -> None:
        self._client = OpenAI(api_key=api_key, base_url=LLM_BASE_URL)

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str = LLM_MODEL_FLASH,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        enable_thinking: bool = False,
    ) -> str:
        """同步调用 LLM。"""
        try:
            kwargs: dict = dict(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                # enable_thinking 非 OpenAI 标准参数，需通过 extra_body 传入
                # qwen3.5 系列默认开启思考，必须显式传 False 才能关闭
                extra_body={"enable_thinking": enable_thinking},
            )
            resp = self._client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.error("LLM 调用失败: %s", e)
            return ""

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = LLM_MODEL_FLASH,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        enable_thinking: bool = False,
    ):
        """流式调用 LLM，返回生成器。yield (type, text)，type 为 'thinking' 或 'content'。"""
        try:
            kwargs: dict = dict(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                extra_body={"enable_thinking": enable_thinking},
            )
            stream = self._client.chat.completions.create(**kwargs)
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                # 深度思考内容通过 reasoning_content 字段返回
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    yield ("thinking", delta.reasoning_content)
                if delta.content:
                    yield ("content", delta.content)
        except Exception as e:
            logger.error("LLM 流式调用失败: %s", e)
