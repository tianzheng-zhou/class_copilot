"""课堂问题自动检测。"""

from __future__ import annotations

import logging

from src.config.constants import LLM_MODEL_FLASH
from src.llm.qwen_client import QwenClient

logger = logging.getLogger(__name__)

QUESTION_DETECTION_PROMPT = """\
你是一个课堂问题检测助手。你的任务是判断下面这段教师的课堂发言中是否包含向学生提出的问题。

判断规则：
1. 教师直接向学生提问（如"同学们觉得呢？""谁来回答一下？""大家想想为什么？"）→ 是问题
2. 反问句、设问句（用于引导思考但需要学生回答的）→ 是问题
3. 教师自问自答、纯粹的陈述、过渡语句 → 不是问题
4. 考虑上下文语境判断

请严格按以下 JSON 格式输出（不要输出其他内容）：
{
  "is_question": true/false,
  "question_text": "提取出的问题（如果是问题的话）",
  "confidence": 0.0-1.0
}

教师发言：
"""


class QuestionDetector:
    """课堂问题检测器。"""

    def __init__(self, client: QwenClient) -> None:
        self._client = client

    def detect(self, teacher_text: str, context: str = "") -> dict | None:
        """检测文本中是否包含问题。

        返回:
            {"is_question": bool, "question_text": str, "confidence": float}
            检测失败返回 None
        """
        if not teacher_text.strip():
            return None

        prompt = QUESTION_DETECTION_PROMPT
        if context:
            prompt += f"\n[上下文]\n{context[-500:]}\n\n[当前发言]\n"
        prompt += teacher_text

        messages = [
            {"role": "system", "content": "你是课堂问题检测AI，只输出JSON格式结果。"},
            {"role": "user", "content": prompt},
        ]

        response = self._client.chat(messages, model=LLM_MODEL_FLASH, temperature=0.3, max_tokens=256)
        if not response:
            return None

        return self._parse_detection_result(response)

    @staticmethod
    def _parse_detection_result(response: str) -> dict | None:
        """解析并验证 LLM 返回的检测结果。"""
        try:
            import json
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            result = json.loads(text)
            # 类型验证
            if not isinstance(result.get("is_question"), bool):
                return None
            if not isinstance(result.get("confidence"), (int, float)):
                return None
            if not isinstance(result.get("question_text"), str):
                result["question_text"] = ""
            return result
        except (json.JSONDecodeError, IndexError, KeyError):
            logger.warning("问题检测结果解析失败: %s", response)
            return None
