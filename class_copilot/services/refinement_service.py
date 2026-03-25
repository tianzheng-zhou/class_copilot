"""精修 ASR 服务 - 使用 DashScope Qwen-ASR 异步文件转写 API 进行高精度离线转写

基于 qwen3-asr-flash-filetrans 模型的异步调用流程:
  1. Files.upload(file_path, purpose="file-extract") → uploaded_files[0]["file_id"]
  2. Files.get(file_id) → output["url"]  (OSS HTTP URL)
  3. Transcription.async_call(model, input={"file_url": url}, parameters={...}) → task_id
  4. Transcription.fetch(task=task_id) 轮询 → result.transcripts[].sentences[]
     时间单位为毫秒。
"""

import asyncio
import time
from pathlib import Path

import dashscope

from class_copilot.config import settings
from class_copilot.logger import refinement_logger


class RefinementService:
    """高精度精修 ASR 服务 - 通过 DashScope 文件转写 API"""

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
        对本地音频文件进行高精度转写（非实时,离线模式）。
        返回: [{"text": str, "start_time": float, "end_time": float}] 或 None
        """
        file_path = Path(audio_file_path)
        if not file_path.exists():
            refinement_logger.error("音频文件不存在: {}", audio_file_path)
            return None

        dashscope.api_key = settings.dashscope_api_key

        try:
            refinement_logger.info("开始精修转写: {}", audio_file_path)

            # ── 步骤1: 上传文件 → file_id ──
            refinement_logger.debug("上传文件到 DashScope...")
            upload_resp = await asyncio.to_thread(
                dashscope.Files.upload,
                file_path=audio_file_path,
                purpose="file-extract",
                api_key=settings.dashscope_api_key,
            )
            if upload_resp.status_code != 200:
                refinement_logger.error("文件上传失败: status={}, resp={}", upload_resp.status_code, upload_resp)
                return None

            output = upload_resp.output
            if not isinstance(output, dict):
                refinement_logger.error("文件上传返回格式异常: {}", output)
                return None

            file_id = ""
            uploaded_files = output.get("uploaded_files", [])
            if uploaded_files and isinstance(uploaded_files, list):
                file_id = uploaded_files[0].get("file_id", "")
            if not file_id:
                refinement_logger.error("未获取到文件ID: {}", output)
                return None

            refinement_logger.debug("文件上传成功: file_id={}", file_id)

            # ── 步骤2: 获取文件 OSS URL ──
            get_resp = await asyncio.to_thread(
                dashscope.Files.get,
                file_id=file_id,
                api_key=settings.dashscope_api_key,
            )
            if get_resp.status_code != 200:
                refinement_logger.error("获取文件URL失败: status={}, resp={}", get_resp.status_code, get_resp)
                return None

            get_output = get_resp.output
            if not isinstance(get_output, dict):
                refinement_logger.error("获取文件URL返回格式异常: {}", get_output)
                return None

            file_url = get_output.get("url", "")
            if not file_url:
                refinement_logger.error("文件URL为空: {}", get_output)
                return None

            refinement_logger.debug("获取到文件URL (长度={})", len(file_url))

            # ── 步骤3: 提交转写任务 (Qwen-ASR 异步调用) ──
            call_params = {
                "model": settings.refined_asr_model,
                "input": {"file_url": file_url},
                "api_key": settings.dashscope_api_key,
            }
            parameters = {}
            if language:
                parameters["language"] = language
            if parameters:
                call_params["parameters"] = parameters

            response = await asyncio.to_thread(
                dashscope.audio.asr.Transcription.async_call,
                **call_params,
            )

            if response.output is None or not isinstance(response.output, dict):
                refinement_logger.error("提交转写任务返回异常: status={}, output={}", response.status_code, response.output)
                return None

            task_id = response.output.get("task_id")
            if not task_id:
                refinement_logger.error("未获取到转写任务ID: {}", response.output)
                return None

            refinement_logger.debug("转写任务已提交: task_id={}", task_id)

            # ── 步骤4: 轮询等待完成 ──
            result = await self._wait_for_task(task_id)
            if result is None:
                return None

            # ── 步骤5: 解析结果 ──
            results = await self._parse_transcription_result(result)

            refinement_logger.info("精修转写完成: {} 个片段, 总文本长度={}",
                                   len(results), sum(len(r["text"]) for r in results))

            # 更新用量估算（基于 128kbps MP3）
            file_size = file_path.stat().st_size
            estimated_duration = file_size / (128 * 1024 / 8)
            self._monthly_usage_seconds += estimated_duration

            return results

        except Exception as e:
            refinement_logger.error("精修转写异常: {}", e, exc_info=True)
            return None

    async def _wait_for_task(self, task_id: str, timeout: int = 600, poll_interval: int = 3) -> dict | None:
        """轮询等待转写任务完成"""
        start = time.time()
        while time.time() - start < timeout:
            response = await asyncio.to_thread(
                dashscope.audio.asr.Transcription.fetch,
                task=task_id,
                api_key=settings.dashscope_api_key,
            )
            if response.output is None or not isinstance(response.output, dict):
                refinement_logger.warning("fetch 返回异常: {}", response.output)
                await asyncio.sleep(poll_interval)
                continue

            status = response.output.get("task_status")
            if status == "SUCCEEDED":
                return response.output
            elif status in ("FAILED", "CANCELED"):
                refinement_logger.error("转写任务失败: status={}, output={}", status, response.output)
                return None
            # PENDING / RUNNING
            await asyncio.sleep(poll_interval)

        refinement_logger.error("转写任务超时: task_id={}", task_id)
        return None

    async def _parse_transcription_result(self, output: dict) -> list[dict]:
        """解析 Qwen-ASR 转写结果，获取文本和时间戳"""
        results = []
        # Qwen-ASR 异步调用结果直接包含 result.transcripts
        result = output.get("result", {})
        transcripts = result.get("transcripts", [])

        for transcript in transcripts:
            sentences = transcript.get("sentences", [])
            if sentences:
                for sent in sentences:
                    results.append({
                        "text": sent.get("text", ""),
                        "start_time": sent.get("begin_time", 0) / 1000.0,
                        "end_time": sent.get("end_time", 0) / 1000.0,
                    })
            else:
                # 没有句级结果时使用整体文本
                text = transcript.get("text", "")
                if text:
                    results.append({
                        "text": text,
                        "start_time": 0,
                        "end_time": 0,
                    })

        return results

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
