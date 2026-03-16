"""阿里云百炼 Qwen LLM 客户端（OpenAI 兼容接口）。"""

from __future__ import annotations

import logging
import time
from collections.abc import Generator

from openai import APIConnectionError, APIError, OpenAI, RateLimitError

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
        retries: int = 2,
    ) -> str:
        """同步调用 LLM，带自动重试。"""
        kwargs: dict = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={"enable_thinking": enable_thinking},
        )
        for attempt in range(retries + 1):
            try:
                resp = self._client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content or ""
            except (APIConnectionError, RateLimitError) as e:
                logger.warning("LLM 调用失败 (尝试 %d/%d): %s", attempt + 1, retries + 1, e)
                if attempt < retries:
                    time.sleep(1)
                else:
                    return ""
            except APIError as e:
                logger.error("LLM API 错误: %s", e)
                return ""
            except Exception as e:
                logger.error("LLM 意外错误: %s", e, exc_info=True)
                return ""
        return ""

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = LLM_MODEL_FLASH,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        enable_thinking: bool = False,
    ) -> Generator[tuple[str, str], None, None]:
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
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    yield ("thinking", delta.reasoning_content)
                if delta.content:
                    yield ("content", delta.content)
        except (APIConnectionError, APIError, RateLimitError) as e:
            logger.error("LLM 流式调用失败: %s", e)
        except Exception as e:
            logger.error("LLM 流式调用意外错误: %s", e, exc_info=True)
