"""加密服务 - API Key 加密存储"""

import os
import base64

from cryptography.fernet import Fernet
from loguru import logger

from class_copilot.config import settings


_fernet = None


def _get_fernet() -> Fernet:
    """获取或创建 Fernet 加密实例"""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = settings.encryption_key
    if not key:
        # 自动生成密钥并保存到 .env
        key = Fernet.generate_key().decode()
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\nCC_ENCRYPTION_KEY={key}\n")
        settings.encryption_key = key
        logger.info("已自动生成加密密钥")

    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_value(plaintext: str) -> str:
    """加密字符串"""
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str) -> str:
    """解密字符串"""
    f = _get_fernet()
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
