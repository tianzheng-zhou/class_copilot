"""英文课堂翻译服务。"""

from __future__ import annotations

import logging

from src.config.constants import LLM_MODEL_FLASH
from src.llm.qwen_client import QwenClient

logger = logging.getLogger(__name__)

TRANSLATE_PROMPT = """\
将以下英文课堂内容翻译为中文，保持学术术语的准确性。只输出翻译结果，不要解释。

英文原文：
{text}
"""


class Translator:
    """英文授课翻译服务。"""

    def __init__(self, client: QwenClient) -> None:
        self._client = client

    def translate_to_chinese(self, english_text: str) -> str:
        if not english_text.strip():
            return ""

        messages = [
            {"role": "system", "content": "你是专业的学术翻译助手，将英文课堂内容翻译为中文。"},
            {"role": "user", "content": TRANSLATE_PROMPT.format(text=english_text)},
        ]
        return self._client.chat(messages, model=LLM_MODEL_FLASH, temperature=0.3, max_tokens=512)
