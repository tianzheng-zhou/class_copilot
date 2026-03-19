"""精修 ASR 服务 - 使用 qwen3-asr-flash 进行高精度文件转写"""

import asyncio
from datetime import datetime
from pathlib import Path

import dashscope

from loguru import logger
from class_copilot.config import settings
from class_copilot.logger import refinement_logger


class RefinementService:
    """高精度精修 ASR 服务"""

    def __init__(self):
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._monthly_usage_seconds: float = 0.0

    async def transcribe_file(
        self,
        audio_file_path: str,
        hot_words: str = "",
        language: str = "zh",
    ) -> list[dict] | None:
        """
        对音频文件进行高精度转写。
        返回转写结果列表: [{"text": str, "start_time": float, "end_time": float, "speaker_label": str}]
        """
        if not Path(audio_file_path).exists():
            refinement_logger.error("音频文件不存在: {}", audio_file_path)
            return None

        dashscope.api_key = settings.dashscope_api_key

        # 构建热词
        vocabulary = None
        if hot_words:
            words = [w.strip() for w in hot_words.split(",") if w.strip()]
            if words:
                vocabulary = [{"text": w, "weight": 4} for w in words]

        try:
            refinement_logger.info("开始精修转写: {}", audio_file_path)

            # 使用 DashScope 文件转写 API
            response = await asyncio.to_thread(
                dashscope.audio.asr.Transcription.call,
                model=settings.refined_asr_model,
                file_urls=[audio_file_path],
                language_hints=[language],
                **({"vocabulary": vocabulary} if vocabulary else {}),
            )

            if response.status_code != 200:
                refinement_logger.error("精修转写API错误: {} - {}", response.status_code, response.message)
                return None

            # 解析结果
            results = []
            transcription_result = response.output
            if transcription_result and "results" in transcription_result:
                for item in transcription_result["results"]:
                    transcript = item.get("transcription_url") or item.get("text", "")
                    # 如果返回的是 URL，需要额外请求获取内容
                    if isinstance(transcript, str) and transcript.startswith("http"):
                        import httpx
                        async with httpx.AsyncClient() as client:
                            resp = await client.get(transcript)
                            transcript_data = resp.json()
                    else:
                        transcript_data = {"transcripts": [{"text": transcript}]}

                    if "transcripts" in transcript_data:
                        for seg in transcript_data["transcripts"]:
                            results.append({
                                "text": seg.get("text", ""),
                                "start_time": seg.get("begin_time", 0) / 1000.0,
                                "end_time": seg.get("end_time", 0) / 1000.0,
                                "speaker_label": seg.get("speaker_id", "UNKNOWN"),
                            })

            refinement_logger.info("精修转写完成: {} 个片段", len(results))

            # 更新用量
            file_size = Path(audio_file_path).stat().st_size
            estimated_duration = file_size / (128 * 1024 / 8)  # 估算基于128kbps MP3
            self._monthly_usage_seconds += estimated_duration

            return results

        except Exception as e:
            refinement_logger.error("精修转写异常: {}", e)
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
        refinement_logger.info("开始课后批量精修: session={}, 共{}个录音", session_id, total)

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
                refinement_logger.warning("精修转写失败，{}秒后重试 ({}/{})", delay, attempt + 1, max_retries)
                await asyncio.sleep(delay)

        refinement_logger.error("精修转写最终失败: {}", audio_path)
        return None

    def cancel_task(self, session_id: str):
        """取消精修任务"""
        if session_id in self._running_tasks:
            self._running_tasks[session_id].cancel()
            refinement_logger.info("已取消精修任务: {}", session_id)

    @property
    def monthly_usage_minutes(self) -> float:
        return self._monthly_usage_seconds / 60
