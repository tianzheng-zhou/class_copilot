"""实时 ASR 服务 - 豆包(火山引擎)流式语音识别 v3 大模型版

基于 WebSocket 二进制协议:
  - 连接: wss://openspeech.bytedance.com/api/v3/sauc/bigmodel
  - 鉴权: HTTP Header (X-Api-App-Key / X-Api-Access-Key / X-Api-Resource-Id)
  - 发送: full client request (JSON) + audio only requests (raw PCM)
  - 接收: full server response (JSON with recognition results)
"""

import asyncio
import gzip
import json
import struct
import uuid

import websockets
from websockets.exceptions import InvalidStatus

from class_copilot.config import settings
from class_copilot.logger import asr_logger

# ── 二进制协议常量 ──
_PROTOCOL_VERSION = 0b0001
_HEADER_SIZE = 0b0001  # 1 × 4 = 4 bytes

_MSG_FULL_CLIENT_REQUEST = 0b0001
_MSG_AUDIO_ONLY = 0b0010
_MSG_FULL_SERVER_RESPONSE = 0b1001
_MSG_ERROR = 0b1111

_FLAG_NONE = 0b0000
_FLAG_LAST_AUDIO = 0b0010

_SERIAL_JSON = 0b0001
_SERIAL_NONE = 0b0000

_COMPRESS_NONE = 0b0000
_COMPRESS_GZIP = 0b0001


def _make_header(msg_type: int, flags: int, serial: int, compress: int) -> bytes:
    return bytes([
        (_PROTOCOL_VERSION << 4) | _HEADER_SIZE,
        (msg_type << 4) | flags,
        (serial << 4) | compress,
        0x00,
    ])


def _pack_full_client_request(payload: dict) -> bytes:
    """构建 full client request 二进制帧"""
    header = _make_header(_MSG_FULL_CLIENT_REQUEST, _FLAG_NONE, _SERIAL_JSON, _COMPRESS_GZIP)
    body = gzip.compress(json.dumps(payload).encode("utf-8"))
    return header + struct.pack(">I", len(body)) + body


def _pack_audio_frame(pcm: bytes, is_last: bool = False) -> bytes:
    """构建 audio only request 二进制帧"""
    flags = _FLAG_LAST_AUDIO if is_last else _FLAG_NONE
    header = _make_header(_MSG_AUDIO_ONLY, flags, _SERIAL_NONE, _COMPRESS_GZIP)
    body = gzip.compress(pcm) if pcm else b""
    return header + struct.pack(">I", len(body)) + body


def _parse_server_frame(data: bytes) -> dict:
    """解析服务端返回的二进制帧"""
    if len(data) < 4:
        return {"type": "unknown", "raw": data}

    msg_type = (data[1] >> 4) & 0x0F
    flags = data[1] & 0x0F
    compress = data[2] & 0x0F

    if msg_type == _MSG_ERROR:
        if len(data) >= 12:
            err_code = struct.unpack(">I", data[4:8])[0]
            err_size = struct.unpack(">I", data[8:12])[0]
            err_msg = data[12:12 + err_size].decode("utf-8", errors="replace")
            return {"type": "error", "code": err_code, "message": err_msg}
        return {"type": "error", "code": -1, "message": "unknown error"}

    if msg_type == _MSG_FULL_SERVER_RESPONSE:
        offset = 4
        # v3 可能包含 sequence number (flags 0b0001=正序列号, 0b0011=负/最后序列号)
        if flags & 0b0001:
            offset += 4  # 跳过 4 字节序列号
        payload_size = struct.unpack(">I", data[offset:offset + 4])[0]
        offset += 4
        payload = data[offset:offset + payload_size]
        if compress == _COMPRESS_GZIP:
            payload = gzip.decompress(payload)
        result = json.loads(payload.decode("utf-8"))
        return {"type": "response", **result}

    return {"type": "unknown", "msg_type": msg_type}


class DoubaoRealtimeASRService:
    """豆包实时 ASR 管理（火山引擎 v3 大模型流式语音识别）"""

    WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

    def __init__(self):
        self._ws = None
        self._recv_task: asyncio.Task | None = None
        self.result_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._disconnected = False
        self._last_error_code: int | None = None

    # ── 公共接口 (与 RealtimeASRService 保持一致) ──

    async def start(self, hot_words: str = "", language: str = "zh"):
        """启动豆包实时 ASR (v3 大模型)"""
        if self._running:
            asr_logger.warning("豆包 ASR 已在运行中")
            return

        appid = settings.doubao_appid
        token = settings.doubao_access_token
        resource_id = settings.doubao_resource_id_streaming

        if not token:
            raise ValueError("豆包 ASR 配置不完整: 请设置 doubao_access_token（新版控制台 API Key）")

        connect_id = str(uuid.uuid4())

        # v3 鉴权通过 HTTP Header
        extra_headers = {
            "X-Api-Resource-Id": resource_id,
            "X-Api-Connect-Id": connect_id,
        }
        # 新版控制台使用 x-api-key，旧版使用 X-Api-App-Key + X-Api-Access-Key
        if appid:
            extra_headers["X-Api-App-Key"] = appid
            extra_headers["X-Api-Access-Key"] = token
        else:
            extra_headers["x-api-key"] = token

        try:
            self._ws = await websockets.connect(
                self.WS_URL,
                additional_headers=extra_headers,
            )
        except InvalidStatus as e:
            body = ""
            if hasattr(e, "response") and e.response.body:
                body = e.response.body.decode("utf-8", errors="replace")
            asr_logger.error("豆包 ASR WebSocket 握手被拒: HTTP {}, body={}", e.response.status_code, body)
            raise ConnectionError(f"豆包 ASR 连接被拒: HTTP {e.response.status_code}, {body}") from e

        # 构建 v3 full client request (无 app 段)
        req_payload = {
            "user": {"uid": "class_copilot_user"},
            "audio": {
                "format": "pcm",
                "rate": settings.sample_rate,
                "bits": 16,
                "channel": settings.channels,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_punc": True,
                "enable_itn": True,
                "enable_ddc": True,
                "show_utterances": True,
                "result_type": "single",
            },
        }

        # v3 热词通过 corpus.context 内联传递
        if hot_words and hot_words.strip():
            words = [w.strip() for w in hot_words.replace("\uff0c", ",").split(",") if w.strip()]
            if words:
                req_payload["request"]["corpus"] = {
                    "context": json.dumps({"hotwords": words}, ensure_ascii=False)
                }

        await self._ws.send(_pack_full_client_request(req_payload))

        # 读取首包响应确认连接成功
        first = await self._ws.recv()
        parsed = _parse_server_frame(first)
        if parsed.get("type") == "error":
            await self._ws.close()
            self._ws = None
            raise ConnectionError(f"豆包 ASR 连接被拒: code={parsed.get('code')}, {parsed.get('message')}")

        self._running = True
        self._disconnected = False
        self._last_error_code = None

        # 启动接收协程
        self._recv_task = asyncio.create_task(self._receive_loop())
        asr_logger.info("豆包实时 ASR 已启动 (v3), resource_id={}, 语言={}", resource_id, language)

    async def send_audio(self, audio_bytes: bytes):
        """发送 PCM 音频帧"""
        if self._ws and self._running and not self._disconnected:
            try:
                await self._ws.send(_pack_audio_frame(audio_bytes))
            except Exception as e:
                if not self._disconnected:
                    self._disconnected = True
                    asr_logger.error("豆包 ASR 发送音频失败: {}", e)

    async def stop(self):
        """停止 ASR"""
        if not self._running:
            return
        try:
            if self._ws:
                try:
                    await self._ws.send(_pack_audio_frame(b"", is_last=True))
                    await asyncio.sleep(0.3)
                except Exception:
                    pass
        finally:
            if self._recv_task:
                self._recv_task.cancel()
                try:
                    await self._recv_task
                except asyncio.CancelledError:
                    pass
                self._recv_task = None

            if self._ws:
                try:
                    await self._ws.close()
                except Exception:
                    pass
                self._ws = None

            self._running = False
            self._disconnected = False
            asr_logger.info("豆包实时 ASR 已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_disconnected(self) -> bool:
        return self._disconnected

    @property
    def is_permanent_error(self) -> bool:
        return self._last_error_code in (401, 403, 1002)

    # ── 内部方法 ──

    async def _receive_loop(self):
        """持续接收并解析服务端响应"""
        try:
            async for message in self._ws:
                if not self._running:
                    break
                parsed = _parse_server_frame(message)

                if parsed["type"] == "error":
                    code = parsed.get("code", -1)
                    asr_logger.error("豆包 ASR 错误: code={}, msg={}", code, parsed.get("message"))
                    self._last_error_code = code
                    self._disconnected = True
                    break

                if parsed["type"] == "response":
                    code = parsed.get("code")
                    # 已知错误码立即中断
                    if code in (45000001, 45000002):
                        asr_logger.error("豆包 ASR 鉴权错误: code={}, msg={}", code, parsed.get("message"))
                        self._last_error_code = 401
                        self._disconnected = True
                        break
                    if code is not None and code not in (0, 20000000):
                        asr_logger.warning("豆包 ASR 非成功响应: code={}, msg={}", code, parsed.get("message"))
                        continue
                    # code=None / 0 / 20000000 均为正常, 尝试提取结果
                    self._dispatch_results(parsed)

        except websockets.ConnectionClosed:
            asr_logger.warning("豆包 ASR WebSocket 连接已关闭")
            self._disconnected = True
        except asyncio.CancelledError:
            pass
        except Exception as e:
            asr_logger.error("豆包 ASR 接收异常: {}", e)
            self._disconnected = True

    def _dispatch_results(self, parsed: dict):
        """从 full server response 中提取识别结果并放入队列"""
        result = parsed.get("result", {})
        utterances = result.get("utterances", [])
        for utt in utterances:
            text = utt.get("text", "")
            if not text.strip():
                continue
            msg = {
                "text": text,
                "is_final": bool(utt.get("definite", False)),
                "start_time": utt.get("start_time", 0) / 1000.0,
                "end_time": utt.get("end_time", 0) / 1000.0,
                "speaker_label": "UNKNOWN",
                "sentence_id": 0,
            }
            asr_logger.debug("豆包ASR [final={}]: {}", msg["is_final"], text)
            self.result_queue.put_nowait(msg)
