"""问题检测服务 - 从转写文本中检测教师问题"""

import asyncio
import time
from difflib import SequenceMatcher

from loguru import logger

from class_copilot.config import settings
from class_copilot.services.llm_service import LLMService
from class_copilot.logger import llm_logger


class QuestionDetector:
    """问题检测器"""

    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service
        self._last_detection_time: float = 0
        self._detected_questions: list[str] = []  # 已检测到的问题列表
        self._buffer: list[dict] = []  # 转写片段缓冲

    def add_transcription(self, segment: dict):
        """
        添加转写片段到缓冲区
        segment: {"text": str, "is_teacher": bool, "is_final": bool, "speaker_label": str}
        """
        if segment.get("is_final"):
            self._buffer.append(segment)
            # 保留最近30条
            if len(self._buffer) > 30:
                self._buffer = self._buffer[-30:]

    def _build_detection_text(self, filter_mode: str = "all") -> str:
        """构建检测用文本"""
        recent = self._buffer[-10:]  # 最近10条

        if filter_mode == "teacher_only":
            # 仅在有说话人信息时过滤，否则使用全部
            teacher_segments = [s for s in recent if s.get("is_teacher", False)]
            segments = teacher_segments if teacher_segments else recent
        else:
            segments = recent

        if not segments:
            return ""

        lines = []
        for s in segments:
            label = s.get("speaker_label", "")
            text = s.get("text", "")
            lines.append(f"[{label}] {text}")

        return "\n".join(lines)

    def _is_duplicate(self, question: str) -> bool:
        """检查是否与已检测到的问题重复（相似度>=80%）"""
        for existing in self._detected_questions:
            ratio = SequenceMatcher(None, question, existing).ratio()
            if ratio >= settings.question_similarity_threshold:
                return True
        return False

    def _check_cooldown(self) -> bool:
        """检查是否在冷却期内"""
        now = time.time()
        if now - self._last_detection_time < settings.question_cooldown_seconds:
            return True
        return False

    async def detect(
        self,
        course_name: str = "",
        language: str = "zh",
        filter_mode: str = "teacher_only",
        force: bool = False,
    ) -> dict | None:
        """
        执行问题检测。
        返回 {"question": str, "confidence": float, "source": str} 或 None。
        """
        # 冷却检查（手动触发不受冷却限制）
        if not force and self._check_cooldown():
            return None

        text = self._build_detection_text(filter_mode)
        if not text:
            return None

        result = await self.llm_service.detect_question(text, course_name, language)
        if result is None:
            return None

        if not result.get("is_question", False):
            return None

        question = result.get("question", "")
        confidence = result.get("confidence", 0.0)

        # 置信度筛选
        if confidence < settings.question_confidence_threshold:
            llm_logger.debug("问题置信度不足: {} < {}", confidence, settings.question_confidence_threshold)
            return None

        # 去重检查（强制触发不去重）
        if not force and self._is_duplicate(question):
            llm_logger.debug("检测到重复问题: {}", question)
            return None

        # 记录检测
        self._last_detection_time = time.time()
        self._detected_questions.append(question)
        # 保留最近50个问题用于去重
        if len(self._detected_questions) > 50:
            self._detected_questions = self._detected_questions[-50:]

        source = "forced" if force else "auto"
        llm_logger.info("检测到新问题 [{}]: {} (置信度: {:.2f})", source, question, confidence)

        return {
            "question": question,
            "confidence": confidence,
            "source": source,
            "context": text,
        }

    def reset(self):
        """重置检测器状态"""
        self._buffer.clear()
        self._detected_questions.clear()
        self._last_detection_time = 0
