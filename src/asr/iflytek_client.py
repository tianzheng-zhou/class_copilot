"""科大讯飞实时语音转写大模型版 WebSocket 客户端。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlencode, urlparse

import websockets.sync.client as ws_sync

from src.config.constants import (
    ASR_LANG,
    ASR_PD,
    ASR_ROLE_TYPE,
    AUDIO_CHUNK_BYTES,
    AUDIO_CHUNK_DURATION_MS,
    IFLYTEK_ASR_WS_URL,
)

logger = logging.getLogger(__name__)


class TranscriptResult:
    """转写结果。"""
    def __init__(self, text: str, speaker: str, is_final: bool,
                 start_ms: int = 0, end_ms: int = 0) -> None:
        self.text = text
        self.speaker = speaker
        self.is_final = is_final
        self.start_ms = start_ms
        self.end_ms = end_ms


class IflytekASRClient:
    """讯飞实时语音转写 WebSocket 客户端。"""

    def __init__(
        self,
        app_id: str,
        access_key_id: str,
        access_key_secret: str,
        on_result: Callable[[TranscriptResult], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_connected: Callable[[], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
        feature_ids: list[str] | None = None,
    ) -> None:
        self._app_id = app_id
        self._access_key_id = access_key_id
        self._access_key_secret = access_key_secret
        self._on_result = on_result
        self._on_error = on_error
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._feature_ids = feature_ids or []

        self._ws = None
        self._running = False
        self._send_thread: threading.Thread | None = None
        self._recv_thread: threading.Thread | None = None
        self._audio_buffer: list[bytes] = []
        self._buffer_lock = threading.Lock()

    def _build_auth_url(self) -> str:
        """构建认证 URL（HMAC-SHA256 签名）。"""
        parsed = urlparse(IFLYTEK_ASR_WS_URL)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%a, %d %b %Y %H:%M:%S GMT")

        signature_origin = (
            f"host: {parsed.hostname}\n"
            f"date: {date_str}\n"
            f"GET {parsed.path} HTTP/1.1"
        )
        signature = base64.b64encode(
            hmac.new(
                self._access_key_secret.encode(),
                signature_origin.encode(),
                hashlib.sha256,
            ).digest()
        ).decode()

        authorization_origin = (
            f'api_key="{self._access_key_id}", '
            f'algorithm="hmac-sha256", '
            f'headers="host date request-line", '
            f'signature="{signature}"'
        )
        authorization = base64.b64encode(authorization_origin.encode()).decode()

        params = {
            "authorization": authorization,
            "date": date_str,
            "host": parsed.hostname,
        }
        return f"{IFLYTEK_ASR_WS_URL}?{urlencode(params)}"

    def _build_first_frame(self) -> dict:
        """构建首帧参数。"""
        business = {
            "language": ASR_LANG,
            "pd": ASR_PD,
            "role_type": ASR_ROLE_TYPE,
            "accent": "mandarin",
        }
        if self._feature_ids:
            business["feature_ids"] = ",".join(self._feature_ids)
            business["eng_spk_match"] = 1

        return {
            "common": {"app_id": self._app_id},
            "business": business,
            "data": {
                "status": 0,
                "format": "audio/L16;rate=16000",
                "encoding": "raw",
            },
        }

    def connect(self) -> None:
        """建立 WebSocket 连接。"""
        if self._running:
            return

        url = self._build_auth_url()
        try:
            self._ws = ws_sync.connect(url, additional_headers={}, close_timeout=5)
            self._running = True

            # 发送首帧
            first_frame = self._build_first_frame()
            self._ws.send(json.dumps(first_frame))

            if self._on_connected:
                self._on_connected()

            self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self._recv_thread.start()

            self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
            self._send_thread.start()

            logger.info("讯飞 ASR 已连接")
        except Exception as e:
            logger.error("讯飞 ASR 连接失败: %s", e)
            if self._on_error:
                self._on_error(f"ASR 连接失败: {e}")
            self._running = False

    def feed_audio(self, pcm_data: bytes) -> None:
        """喂入音频数据。"""
        if not self._running:
            return
        with self._buffer_lock:
            self._audio_buffer.append(pcm_data)

    def _send_loop(self) -> None:
        """持续发送音频数据。"""
        while self._running and self._ws:
            chunk = None
            with self._buffer_lock:
                if self._audio_buffer:
                    chunk = self._audio_buffer.pop(0)

            if chunk:
                try:
                    audio_b64 = base64.b64encode(chunk).decode()
                    frame = {
                        "data": {
                            "status": 1,
                            "format": "audio/L16;rate=16000",
                            "encoding": "raw",
                            "audio": audio_b64,
                        }
                    }
                    self._ws.send(json.dumps(frame))
                except Exception as e:
                    logger.error("发送音频数据错误: %s", e)
                    if self._on_error:
                        self._on_error(str(e))
                    break
            else:
                time.sleep(AUDIO_CHUNK_DURATION_MS / 1000)

    def _receive_loop(self) -> None:
        """接收转写结果。"""
        while self._running and self._ws:
            try:
                msg = self._ws.recv(timeout=5)
                if msg:
                    self._handle_message(json.loads(msg))
            except TimeoutError:
                continue
            except Exception as e:
                if self._running:
                    logger.error("接收结果错误: %s", e)
                    if self._on_error:
                        self._on_error(str(e))
                break

        self._running = False
        if self._on_disconnected:
            self._on_disconnected()

    def _handle_message(self, msg: dict) -> None:
        """解析讯飞返回的消息。"""
        code = msg.get("code", -1)
        if code != 0:
            error_msg = msg.get("message", "未知错误")
            logger.error("ASR 错误 [%s]: %s", code, error_msg)
            if self._on_error:
                self._on_error(f"ASR 错误: {error_msg}")
            return

        data = msg.get("data", {})
        result = data.get("result", {})
        if not result:
            return

        # 解析转写文本
        ws_list = result.get("ws", [])
        text_parts = []
        for ws in ws_list:
            for cw in ws.get("cw", []):
                text_parts.append(cw.get("w", ""))

        text = "".join(text_parts).strip()
        if not text:
            return

        speaker = str(result.get("spk", result.get("role", "")))
        is_final = result.get("ls", False)
        bg = result.get("bg", 0)  # 开始时间（毫秒）
        ed = result.get("ed", 0)  # 结束时间

        if self._on_result:
            self._on_result(TranscriptResult(
                text=text,
                speaker=speaker,
                is_final=is_final,
                start_ms=bg,
                end_ms=ed,
            ))

    def disconnect(self) -> None:
        """断开连接。"""
        self._running = False

        if self._ws:
            try:
                # 发送结束帧
                end_frame = {"data": {"status": 2}}
                self._ws.send(json.dumps(end_frame))
                self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._send_thread:
            self._send_thread.join(timeout=3)
            self._send_thread = None
        if self._recv_thread:
            self._recv_thread.join(timeout=3)
            self._recv_thread = None

        logger.info("讯飞 ASR 已断开")

    @property
    def is_connected(self) -> bool:
        return self._running
