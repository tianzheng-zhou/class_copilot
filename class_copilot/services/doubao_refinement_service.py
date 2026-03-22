"""精修 ASR 服务 - 豆包(火山引擎)录音文件识别 v3 大模型版

API 流程:
  1. POST /api/v3/auc/bigmodel/submit  → 提交任务, 获取 id
  2. POST /api/v3/auc/bigmodel/query   → 轮询查询, code==20000000 表示完成
  返回 result.utterances[]{text, start_time, end_time}
  时间单位为毫秒。

鉴权: HTTP Header (X-Api-App-Key / X-Api-Access-Key / X-Api-Resource-Id)

注意: 该服务需要音频文件可通过 URL 下载。本地录音需通过本应用提供的
/api/recordings/<filename> 端点访问, 并配置 doubao_audio_base_url。
"""

import asyncio
import time
import uuid
from pathlib import Path

import httpx

from class_copilot.config import settings
from class_copilot.logger import refinement_logger


class DoubaoRefinementService:
    """豆包录音文件识别服务 (火山引擎 v3 大模型版)"""

    SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
    QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"

    def __init__(self):
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._monthly_usage_seconds: float = 0.0

    # ── 公共接口 (与 RefinementService 保持一致) ──

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

        appid = settings.doubao_appid
        token = settings.doubao_access_token
        resource_id = settings.doubao_resource_id_offline

        if not token:
            refinement_logger.error("豆包离线 ASR 配置不完整: 请设置 doubao_access_token（新版控制台 API Key）")
            return None

        # 构建音频 URL
        audio_base = settings.doubao_audio_base_url
        if not audio_base:
            refinement_logger.error("豆包离线 ASR 需配置 doubao_audio_base_url (例如 http://your-server:8765/api/recordings)")
            return None

        audio_url = f"{audio_base.rstrip('/')}/{file_path.name}"

        ext = file_path.suffix.lower().lstrip(".")
        fmt_map = {"mp3": "mp3", "wav": "wav", "ogg": "ogg", "mp4": "mp4"}

        request_id = str(uuid.uuid4())

        # v3 鉴权通过 HTTP Header
        headers = {
            "Content-Type": "application/json",
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }
        # 新版控制台使用 x-api-key，旧版使用 X-Api-App-Key + X-Api-Access-Key
        if appid:
            headers["X-Api-App-Key"] = appid
            headers["X-Api-Access-Key"] = token
        else:
            headers["x-api-key"] = token

        # v3 请求体 (无 app 段)
        submit_body = {
            "audio": {
                "format": fmt_map.get(ext, "mp3"),
                "url": audio_url,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": True,
                "show_utterances": True,
                "enable_speaker_info": True,
            },
        }

        try:
            refinement_logger.info("提交豆包录音文件识别 (v3): {}", audio_url)

            # ── 步骤 1: 提交任务 ──
            # v3 submit 响应 body 为空，状态通过 X-Api-Status-Code header 返回
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self.SUBMIT_URL, json=submit_body, headers=headers)
                resp.raise_for_status()

            status_code = resp.headers.get("X-Api-Status-Code", "")
            status_msg = resp.headers.get("X-Api-Message", "")
            logid = resp.headers.get("X-Tt-Logid", "")

            if status_code not in ("20000000",):
                refinement_logger.error("豆包提交任务失败: status={}, msg={}, logid={}", status_code, status_msg, logid)
                return None

            refinement_logger.debug("豆包转写任务已提交: request_id={}, logid={}", request_id, logid)

            # ── 步骤 2: 轮询等待 ──
            result = await self._wait_for_task(request_id, headers)
            if result is None:
                return None

            # ── 步骤 3: 解析结果 ──
            segments = self._parse_result(result)
            refinement_logger.info("豆包精修转写完成: {} 个片段, 总文本长度={}",
                                   len(segments), sum(len(s["text"]) for s in segments))

            # 更新用量估算
            file_size = file_path.stat().st_size
            estimated_duration = file_size / (128 * 1024 / 8)
            self._monthly_usage_seconds += estimated_duration

            return segments

        except Exception as e:
            refinement_logger.error("豆包精修转写异常: {}", e, exc_info=True)
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
        refinement_logger.info("开始豆包课后批量精修: session={}, 共{}个录音", session_id, total)

        for i, path in enumerate(recording_paths):
            if session_id in self._running_tasks and self._running_tasks[session_id].cancelled():
                refinement_logger.info("精修任务已取消: {}", session_id)
                break

            result = await self._transcribe_with_retry(path, hot_words, language)
            progress = (i + 1) / total

            if progress_callback:
                await progress_callback(session_id, progress, result, path)

            refinement_logger.info("精修进度: {}/{} ({:.0%})", i + 1, total, progress)

    def cancel_task(self, session_id: str):
        if session_id in self._running_tasks:
            self._running_tasks[session_id].cancel()
            refinement_logger.info("已取消精修任务: {}", session_id)

    @property
    def monthly_usage_minutes(self) -> float:
        return self._monthly_usage_seconds / 60

    # ── 内部方法 ──

    async def _wait_for_task(
        self, request_id: str, headers: dict, timeout: int = 600, interval: int = 3
    ) -> dict | None:
        """轮询查询转写结果"""
        # v3 query: task ID 通过 X-Api-Request-Id header 传递，body 为空 JSON
        query_headers = {**headers}
        query_headers["X-Api-Request-Id"] = request_id
        query_headers.pop("X-Api-Sequence", None)

        start = time.time()
        while time.time() - start < timeout:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(self.QUERY_URL, json={}, headers=query_headers)
                    resp.raise_for_status()
            except Exception as e:
                refinement_logger.warning("豆包查询异常: {}", e)
                await asyncio.sleep(interval)
                continue

            status_code = resp.headers.get("X-Api-Status-Code", "")

            if status_code == "20000000":
                # 成功，解析 body
                try:
                    return resp.json()
                except Exception:
                    return {"result": {"text": resp.text}}
            elif status_code in ("20000001", "20000002"):
                # 20000001=处理中, 20000002=排队中
                await asyncio.sleep(interval)
            else:
                msg = resp.headers.get("X-Api-Message", "")
                refinement_logger.error("豆包转写查询失败: status={}, msg={}", status_code, msg)
                return None

        refinement_logger.error("豆包转写任务超时: request_id={}", request_id)
        return None

    @staticmethod
    def _parse_result(resp_data: dict) -> list[dict]:
        """解析转写结果为统一格式"""
        results = []
        result = resp_data.get("result", {})
        for utt in result.get("utterances", []):
            text = utt.get("text", "")
            if not text.strip():
                continue
            results.append({
                "text": text,
                "start_time": utt.get("start_time", 0) / 1000.0,
                "end_time": utt.get("end_time", 0) / 1000.0,
            })

        # 回退到整体文本
        if not results:
            text = result.get("text", "") or resp_data.get("text", "")
            if text.strip():
                results.append({"text": text, "start_time": 0, "end_time": 0})

        return results

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
                refinement_logger.warning("豆包精修转写失败，{}秒后重试 ({}/{})", delay, attempt + 1, max_retries)
                await asyncio.sleep(delay)
