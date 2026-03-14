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
    ) -> str:
        """同步调用 LLM。"""
        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
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
    ):
        """流式调用 LLM，返回生成器。"""
        try:
            stream = self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
        except Exception as e:
            logger.error("LLM 流式调用失败: %s", e)
