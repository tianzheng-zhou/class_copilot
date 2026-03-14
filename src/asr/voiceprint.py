"""讯飞声纹管理 API。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import aiohttp

from src.config.constants import (
    IFLYTEK_VOICEPRINT_BASE_URL,
    IFLYTEK_VOICEPRINT_DELETE,
    IFLYTEK_VOICEPRINT_REGISTER,
    IFLYTEK_VOICEPRINT_UPDATE,
)

logger = logging.getLogger(__name__)


class VoiceprintManager:
    """讯飞云端声纹注册/更新/删除。"""

    def __init__(self, app_id: str, access_key_id: str, access_key_secret: str) -> None:
        self._app_id = app_id
        self._access_key_id = access_key_id
        self._access_key_secret = access_key_secret

    def _build_auth_headers(self, method: str, path: str) -> dict[str, str]:
        """构建认证头。"""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
        host = IFLYTEK_VOICEPRINT_BASE_URL.replace("https://", "").replace("http://", "")

        signature_origin = (
            f"host: {host}\n"
            f"date: {date_str}\n"
            f"{method} {path} HTTP/1.1"
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

        return {
            "Authorization": authorization,
            "Date": date_str,
            "Host": host,
            "Content-Type": "application/json",
        }

    async def register(self, audio_data: bytes, feature_info: str = "") -> str | None:
        """注册声纹，返回 feature_id。"""
        path = IFLYTEK_VOICEPRINT_REGISTER
        headers = self._build_auth_headers("POST", path)
        url = f"{IFLYTEK_VOICEPRINT_BASE_URL}{path}"

        payload = {
            "common": {"app_id": self._app_id},
            "business": {
                "feature_info": feature_info,
            },
            "data": {
                "audio": base64.b64encode(audio_data).decode(),
                "format": "audio/L16;rate=16000",
                "encoding": "raw",
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                result = await resp.json()
                if result.get("code") == 0:
                    feature_id = result.get("data", {}).get("feature_id", "")
                    logger.info("声纹注册成功: %s", feature_id)
                    return feature_id
                else:
                    logger.error("声纹注册失败: %s", result)
                    return None

    async def update(self, feature_id: str, audio_data: bytes) -> bool:
        """更新声纹。"""
        path = IFLYTEK_VOICEPRINT_UPDATE
        headers = self._build_auth_headers("POST", path)
        url = f"{IFLYTEK_VOICEPRINT_BASE_URL}{path}"

        payload = {
            "common": {"app_id": self._app_id},
            "business": {"feature_id": feature_id},
            "data": {
                "audio": base64.b64encode(audio_data).decode(),
                "format": "audio/L16;rate=16000",
                "encoding": "raw",
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                result = await resp.json()
                if result.get("code") == 0:
                    logger.info("声纹更新成功: %s", feature_id)
                    return True
                else:
                    logger.error("声纹更新失败: %s", result)
                    return False

    async def delete(self, feature_id: str) -> bool:
        """删除声纹。"""
        path = IFLYTEK_VOICEPRINT_DELETE
        headers = self._build_auth_headers("POST", path)
        url = f"{IFLYTEK_VOICEPRINT_BASE_URL}{path}"

        payload = {
            "common": {"app_id": self._app_id},
            "business": {"feature_id": feature_id},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                result = await resp.json()
                if result.get("code") == 0:
                    logger.info("声纹删除成功: %s", feature_id)
                    return True
                else:
                    logger.error("声纹删除失败: %s", result)
                    return False
