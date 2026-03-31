"""精修 ASR 服务 - 基于 Qwen3.5-Omni 全模态模型 (Chat Completion API)

API 流程:
  1. 读取本地音频文件 → base64 编码
  2. 通过 OpenAI 兼容的 /chat/completions 接口发送 input_audio + 转写指令
  3. 流式收集文本结果
  模型: qwen3.5-omni-flash / qwen3.5-omni-plus
  音频限制: 最长 3 小时 (Qwen3.5-Omni 系列)
  必须 stream=True
"""

import asyncio
import base64
import re
import time
from pathlib import Path

from openai import AsyncOpenAI

from class_copilot.config import settings
from class_copilot.logger import refinement_logger


def _build_refinement_prompt(language: str = "zh", hot_words: str = "") -> str:
    """构建精修转写的系统提示词 (XML 结构)"""
    lang_desc = {
        "zh": "中文（普通话）",
        "en": "English",
    }.get(language, language)

    hot_words_section = ""
    if hot_words and hot_words.strip():
        words = [w.strip() for w in hot_words.replace("\uff0c", ",").split(",") if w.strip()]
        if words:
            words_list = "\n".join(f"    <word>{w}</word>" for w in words)
            hot_words_section = f"""
<hot_words>
  <description>以下是本次课堂中可能出现的专业术语和高频词汇，请确保拼写正确。</description>
  <words>
{words_list}
  </words>
</hot_words>"""

    return f"""<role>
  <identity>你是一个专业的课堂录音转写助手。</identity>
  <task>你的唯一任务是将输入的音频录音精准地转录为文字。</task>
</role>

<transcription_rules>
  <language>{lang_desc}</language>
  <guidelines>
    <rule>严格按照说话人的原话进行逐字转录，保持原始表述。</rule>
    <rule>正确使用标点符号，句子结束时添加句号、问号或感叹号。</rule>
    <rule>对于专业术语、人名、地名等，优先使用通用的正确拼写。</rule>
    <rule>保留口语化表达和语气词，保持转录的真实性。</rule>
    <rule>数字、公式、单位等按照学术规范转写。</rule>
    <rule>段落之间使用换行分隔，使文本易于阅读。</rule>
  </guidelines>
</transcription_rules>

<context>
  <scenario>大学课堂录音的离线转写</scenario>
  <audio_environment>课堂环境录音</audio_environment>
  <primary_speaker>授课教师</primary_speaker>
</context>{hot_words_section}

<output_format>
  <instruction>使用带时间戳的字幕格式输出转录文本。每段文字前标注起止时间，格式为 [HH:MM:SS,mmm --> HH:MM:SS,mmm]。
例如：
[00:00:01,200 --> 00:00:05,800] 今天我们来讲一下线性代数的基本概念。
[00:00:06,100 --> 00:00:12,300] 首先，什么是向量空间？
不要添加任何解释、翻译、总结或额外内容。</instruction>
</output_format>"""


# 匹配 [HH:MM:SS,mmm --> HH:MM:SS,mmm] 文本  或  [MM:SS,mmm --> MM:SS,mmm] 文本
_TS_PATTERN = re.compile(
    r'\[(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\]\s*(.+)',
)


def _ts_to_seconds(ts: str) -> float:
    """将 HH:MM:SS,mmm 或 MM:SS,mmm 转为秒"""
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return 0


def _parse_timestamped_text(text: str) -> list[dict]:
    """解析模型输出的带时间戳字幕格式，回退到纯文本"""
    segments = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        m = _TS_PATTERN.match(line)
        if m:
            segments.append({
                "text": m.group(3).strip(),
                "start_time": _ts_to_seconds(m.group(1)),
                "end_time": _ts_to_seconds(m.group(2)),
            })
        elif line:
            # 没有时间戳的行，追加到上一个片段或创建新片段
            if segments and segments[-1]["end_time"] == 0:
                segments[-1]["text"] += "\n" + line
            else:
                segments.append({"text": line, "start_time": 0, "end_time": 0})
    return segments


class QwenOmniRefinementService:
    """精修 ASR 服务 - 通过 Qwen3.5-Omni Chat Completion API"""

    def __init__(self):
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._monthly_usage_seconds: float = 0.0
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=settings.dashscope_api_key,
                base_url=settings.llm_base_url,
            )
        return self._client

    async def transcribe_file(
        self,
        audio_file_path: str,
        hot_words: str = "",
        language: str = "zh",
    ) -> list[dict] | None:
        """
        对音频文件进行高精度转写。
        返回: [{"text": str, "start_time": float, "end_time": float}] 或 None
        """
        file_path = Path(audio_file_path)
        if not file_path.exists():
            refinement_logger.error("音频文件不存在: {}", audio_file_path)
            return None

        model = settings.refined_asr_model
        if not model or model.startswith("qwen3-asr"):
            model = "qwen3.5-omni-flash"

        ext = file_path.suffix.lower().lstrip(".")
        fmt_map = {"mp3": "mp3", "wav": "wav", "ogg": "ogg", "flac": "flac"}
        audio_format = fmt_map.get(ext, "mp3")

        try:
            refinement_logger.info("开始 Omni 精修转写: {}, model={}", audio_file_path, model)

            # 读取并 base64 编码
            raw = await asyncio.to_thread(file_path.read_bytes)
            audio_b64 = base64.b64encode(raw).decode("ascii")

            system_prompt = _build_refinement_prompt(language=language, hot_words=hot_words)
            client = self._get_client()

            # 流式请求
            stream = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": f"data:;base64,{audio_b64}",
                                    "format": audio_format,
                                },
                            },
                            {"type": "text", "text": "请转录这段音频。"},
                        ],
                    },
                ],
                modalities=["text"],
                stream=True,
                stream_options={"include_usage": True},
            )

            # 收集流式文本
            full_text = ""
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    full_text += chunk.choices[0].delta.content

            if not full_text.strip():
                refinement_logger.warning("Omni 精修转写结果为空")
                return None

            # 解析带时间戳的字幕格式
            segments = _parse_timestamped_text(full_text)

            refinement_logger.info(
                "Omni 精修转写完成: {} 个片段, 总文本长度={}",
                len(segments), sum(len(s["text"]) for s in segments),
            )

            # 更新用量估算（基于 128kbps MP3）
            file_size = file_path.stat().st_size
            estimated_duration = file_size / (128 * 1024 / 8)
            self._monthly_usage_seconds += estimated_duration

            return segments

        except Exception as e:
            refinement_logger.error("Omni 精修转写异常: {}", e, exc_info=True)
            return None

    async def start_post_session_refinement(
        self,
        session_id: str,
        recording_paths: list[str],
        hot_words: str = "",
        language: str = "zh",
        progress_callback=None,
    ):
        """课后批量精修"""
        total = len(recording_paths)
        refinement_logger.info("开始 Omni 课后批量精修: session={}, 共{}个录音", session_id, total)

        for i, path in enumerate(recording_paths):
            if session_id in self._running_tasks and self._running_tasks[session_id].cancelled():
                refinement_logger.info("精修任务已取消: {}", session_id)
                break

            result = await self._transcribe_with_retry(path, hot_words, language)
            progress = (i + 1) / total

            if progress_callback:
                await progress_callback(session_id, progress, result, path)

            refinement_logger.info("精修进度: {}/{} ({:.0%})", i + 1, total, progress)

    async def _transcribe_with_retry(
        self,
        audio_path: str,
        hot_words: str = "",
        language: str = "zh",
        max_retries: int = 3,
    ) -> list[dict] | None:
        """带重试的转写"""
        delays = [10, 30, 60]
        for attempt in range(max_retries):
            result = await self.transcribe_file(audio_path, hot_words, language)
            if result is not None:
                return result
            if attempt < max_retries - 1:
                delay = delays[attempt]
                refinement_logger.warning("Omni 精修转写失败，{}秒后重试 ({}/{})", delay, attempt + 1, max_retries)
                await asyncio.sleep(delay)

        refinement_logger.error("Omni 精修转写最终失败: {}", audio_path)
        return None

    def cancel_task(self, session_id: str):
        if session_id in self._running_tasks:
            self._running_tasks[session_id].cancel()
            refinement_logger.info("已取消精修任务: {}", session_id)

    @property
    def monthly_usage_minutes(self) -> float:
        return self._monthly_usage_seconds / 60
