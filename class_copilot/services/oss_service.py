"""阿里云 OSS 文件上传服务

用于将本地音频文件上传到 OSS，生成带签名的公网可访问 URL，
供豆包离线 ASR 等需要 URL 的服务使用。
"""

import asyncio
from pathlib import Path

import oss2

from class_copilot.config import settings
from class_copilot.logger import refinement_logger


class OSSService:
    """阿里云 OSS 上传 & 签名 URL 服务"""

    def __init__(self):
        self._bucket: oss2.Bucket | None = None

    def _get_bucket(self) -> oss2.Bucket:
        """获取 / 重建 OSS Bucket 实例"""
        ak_id = settings.oss_access_key_id
        ak_secret = settings.oss_access_key_secret
        endpoint = settings.oss_endpoint
        bucket_name = settings.oss_bucket_name

        if not all([ak_id, ak_secret, endpoint, bucket_name]):
            raise ValueError("OSS 配置不完整，请在设置中配置 Access Key、Endpoint 和 Bucket")

        auth = oss2.Auth(ak_id, ak_secret)
        self._bucket = oss2.Bucket(auth, endpoint, bucket_name)
        return self._bucket

    # ── 同步核心方法 (在线程池中运行) ──

    def _upload_sync(self, local_path: str, object_key: str) -> str:
        """同步上传文件并返回签名 URL"""
        bucket = self._get_bucket()
        bucket.put_object_from_file(object_key, local_path)
        expiry = settings.oss_url_expiry_seconds
        url = bucket.sign_url("GET", object_key, expiry)
        return url

    def _test_sync(self) -> dict:
        """同步测试连接"""
        bucket = self._get_bucket()
        info = bucket.get_bucket_info()
        return {
            "bucket": info.name,
            "location": info.location,
            "creation_date": info.creation_date,
        }

    # ── 异步公共接口 ──

    async def upload_file(self, local_path: str) -> str | None:
        """
        上传本地文件到 OSS 并返回签名 URL。

        :param local_path: 本地音频文件绝对路径
        :return: 签名 URL 或 None（失败时）
        """
        file_path = Path(local_path)
        if not file_path.exists():
            refinement_logger.error("OSS 上传失败: 文件不存在 {}", local_path)
            return None

        prefix = (settings.oss_upload_prefix or "class_copilot").strip("/")
        object_key = f"{prefix}/{file_path.name}"

        try:
            url = await asyncio.to_thread(self._upload_sync, str(file_path), object_key)
            refinement_logger.info("OSS 上传成功: {} → {}", file_path.name, object_key)
            return url
        except Exception as e:
            refinement_logger.error("OSS 上传异常: {}", e, exc_info=True)
            return None

    async def test_connection(self) -> dict:
        """测试 OSS 连接是否正常，返回 bucket 信息"""
        return await asyncio.to_thread(self._test_sync)


# 全局单例
oss_service = OSSService()
