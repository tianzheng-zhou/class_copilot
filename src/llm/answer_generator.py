"""智能答案生成。"""

from __future__ import annotations

import logging

from src.config.constants import LLM_MODEL_FLASH
from src.llm.qwen_client import QwenClient

logger = logging.getLogger(__name__)

ANSWER_SYSTEM_PROMPT = """\
你是一个大学生，正在课堂上回答老师的问题。请按照以下要求生成答案：

1. **口语化**：像学生在课堂上口头回答一样，自然流畅，不要太书面化
2. **立场正确**：符合正确价值观
3. **基于上下文**：根据课堂内容来回答，不要凭空编造
4. **不需要引用出处**：保持自然口语风格

课程名称：{course_name}
"""

CONCISE_PROMPT = """\
请用简洁的方式回答以下问题（2-3句话即可），像课堂上快速举手回答一样简短有力。

课堂上下文：
{context}

问题：{question}
"""

DETAILED_PROMPT = """\
请详细回答以下问题（5-8句话），像课堂上被老师追问时的展开回答，内容充实但仍保持口语化。

课堂上下文：
{context}

问题：{question}
"""


class AnswerGenerator:
    """课堂答案生成器。"""

    def __init__(self, client: QwenClient) -> None:
        self._client = client

    def generate(
        self,
        question: str,
        context: str,
        course_name: str = "",
        language: str = "zh",
    ) -> tuple[str, str]:
        """生成简洁版和展开版答案。

        返回: (concise_answer, detailed_answer)
        """
        system = ANSWER_SYSTEM_PROMPT.format(course_name=course_name or "未知课程")
        if language == "en":
            system += "\n请同时用英文和中文回答。先英文，再给出中文翻译。"

        concise_msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": CONCISE_PROMPT.format(
                context=context[-2000:], question=question
            )},
        ]
        detailed_msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": DETAILED_PROMPT.format(
                context=context[-2000:], question=question
            )},
        ]

        concise = self._client.chat(concise_msgs, model=LLM_MODEL_FLASH, temperature=0.7)
        detailed = self._client.chat(detailed_msgs, model=LLM_MODEL_FLASH, temperature=0.7)

        return concise, detailed

    def generate_concise(self, question: str, context: str, course_name: str = "", language: str = "zh") -> str:
        system = ANSWER_SYSTEM_PROMPT.format(course_name=course_name or "未知课程")
        if language == "en":
            system += "\n请同时用英文和中文回答。先英文，再给出中文翻译。"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": CONCISE_PROMPT.format(
                context=context[-2000:], question=question
            )},
        ]
        return self._client.chat(messages, model=LLM_MODEL_FLASH, temperature=0.7)

    def generate_detailed(self, question: str, context: str, course_name: str = "", language: str = "zh") -> str:
        system = ANSWER_SYSTEM_PROMPT.format(course_name=course_name or "未知课程")
        if language == "en":
            system += "\n请同时用英文和中文回答。先英文，再给出中文翻译。"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": DETAILED_PROMPT.format(
                context=context[-2000:], question=question
            )},
        ]
        return self._client.chat(messages, model=LLM_MODEL_FLASH, temperature=0.7)
