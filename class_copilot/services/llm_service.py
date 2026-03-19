"""LLM 服务 - 问题检测与答案生成"""

import asyncio
import json
from typing import AsyncGenerator

from openai import AsyncOpenAI
from loguru import logger

from class_copilot.config import settings
from class_copilot.logger import llm_logger


class LLMService:
    """LLM 集成服务"""

    def __init__(self):
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=settings.dashscope_api_key,
                base_url=settings.llm_base_url,
            )
        return self._client

    def update_api_key(self, api_key: str):
        """更新 API Key"""
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=settings.llm_base_url,
        )

    # ──────────── 问题检测 ────────────

    async def detect_question(
        self,
        transcription_text: str,
        course_name: str = "",
        language: str = "zh",
    ) -> dict | None:
        """
        检测转写文本中是否包含教师提出的问题。
        返回 {"is_question": bool, "question": str, "confidence": float} 或 None。
        """
        system_prompt = """你是一个课堂问题检测助手。你的任务是分析课堂转写文本，判断教师是否在提问。

判断标准：
1. 疑问句式（谁、什么、为什么、怎么、如何、是不是、对不对等）
2. 要求学生回答的语句（"大家想想"、"谁来回答"、"有没有同学知道"等）
3. 开放性讨论邀请（"你们觉得呢"、"有什么看法"等）

注意排除：
- 修辞性提问（反问，不需要回答的问题）
- 自问自答的过渡性语句
- 不完整的句子

请以 JSON 格式返回结果：
{"is_question": true/false, "question": "提取出的问题原文", "confidence": 0.0~1.0}

仅返回 JSON，不要其他内容。"""

        user_content = f"课程：{course_name}\n\n最近的转写文本：\n{transcription_text}"

        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=settings.llm_model_fast,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                max_tokens=200,
                response_format={"type": "json_object"},
            )

            result_text = response.choices[0].message.content.strip()
            result = json.loads(result_text)
            llm_logger.info("问题检测结果: {}", result)
            return result

        except Exception as e:
            llm_logger.error("问题检测失败: {}", e)
            return None

    # ──────────── 答案生成 ────────────

    async def generate_answer(
        self,
        question: str,
        context: str,
        course_name: str = "",
        answer_type: str = "brief",
        language: str = "zh",
    ) -> AsyncGenerator[str, None]:
        """
        流式生成答案。answer_type: brief(简洁版) / detailed(展开版)
        """
        if answer_type == "brief":
            style_instruction = "请用2-3句话简洁回答，像学生在课堂上口头回答一样，自然流畅。"
        else:
            style_instruction = "请用5-8句话详细回答，像学生在课堂上从容展开回答一样，条理清晰、自然流畅。"

        if language == "en":
            style_instruction += "\n请用英文回答，同时附上中文翻译。"

        system_prompt = f"""你是一个大学生，正在课堂上回答老师的问题。

要求：
- {style_instruction}
- 口语化表达，不要书面化
- 回答要符合课程语境
- 不需要说"老师好"之类的开场白，直接回答问题
- 回答内容要准确、得体"""

        user_content = f"课程：{course_name}\n\n课堂上下文：\n{context}\n\n老师的问题：{question}"

        try:
            client = self._get_client()
            stream = await client.chat.completions.create(
                model=settings.llm_model_fast,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.7,
                max_tokens=500 if answer_type == "brief" else 1000,
                stream=True,
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            llm_logger.error("答案生成失败 [{}]: {}", answer_type, e)
            yield f"[答案生成失败: {e}]"

    async def generate_answer_full(
        self,
        question: str,
        context: str,
        course_name: str = "",
        answer_type: str = "brief",
        language: str = "zh",
    ) -> str:
        """非流式生成完整答案"""
        parts = []
        async for chunk in self.generate_answer(question, context, course_name, answer_type, language):
            parts.append(chunk)
        return "".join(parts)

    # ──────────── 主动提问 ────────────

    async def chat(
        self,
        user_question: str,
        context: str,
        course_name: str = "",
        model: str | None = None,
        think_mode: bool = False,
    ) -> AsyncGenerator[str, None]:
        """主动提问，流式返回 AI 回答"""
        use_model = model or settings.llm_model_quality

        system_prompt = f"""你是一个知识渊博的 AI 助手，正在帮助学生理解课堂内容。

当前课程：{course_name if course_name else '未指定'}

以下是课堂转写记录，请基于此上下文回答学生的问题：
{context[-4000:] if len(context) > 4000 else context}

要求：
- 回答准确、清晰
- 结合课堂内容进行解答
- 支持 Markdown 格式
- 如果问题与课堂内容无关，仍尽力回答"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_question},
        ]

        try:
            client = self._get_client()
            extra_params = {}
            if think_mode:
                extra_params["extra_body"] = {"enable_thinking": True}

            stream = await client.chat.completions.create(
                model=use_model,
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
                stream=True,
                **extra_params,
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            llm_logger.error("主动提问失败: {}", e)
            yield f"[回答失败: {e}]"

    # ──────────── 翻译 ────────────

    async def translate(self, text: str, target_lang: str = "zh") -> str | None:
        """翻译文本"""
        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=settings.llm_model_fast,
                messages=[
                    {"role": "system", "content": f"请将以下文本翻译为{'中文' if target_lang == 'zh' else 'English'}，只返回翻译结果："},
                    {"role": "user", "content": text},
                ],
                temperature=0.1,
                max_tokens=1000,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            llm_logger.error("翻译失败: {}", e)
            return None
