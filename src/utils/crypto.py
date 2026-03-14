"""API Key 加密存储。使用 Fernet 对称加密。"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class KeyVault:
    """加密存储 API Key。"""

    def __init__(self, vault_path: str | Path) -> None:
        self._vault_path = Path(vault_path)
        self._vault_path.parent.mkdir(parents=True, exist_ok=True)
        self._salt_path = self._vault_path.with_suffix(".salt")
        self._fernet = self._init_fernet()

    def _init_fernet(self) -> Fernet:
        if self._salt_path.exists():
            salt = self._salt_path.read_bytes()
        else:
            salt = os.urandom(16)
            self._salt_path.write_bytes(salt)

        # 使用机器名 + 用户名作为密码派生源
        machine_key = f"{os.environ.get('COMPUTERNAME', '')}-{os.environ.get('USERNAME', '')}".encode()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(machine_key))
        return Fernet(key)

    def store(self, name: str, value: str) -> None:
        """加密存储一个 key-value。"""
        data: dict[str, str] = self._load_all()
        data[name] = self._fernet.encrypt(value.encode()).decode()
        self._save_all(data)

    def retrieve(self, name: str) -> str | None:
        """取出解密后的值。"""
        data = self._load_all()
        encrypted = data.get(name)
        if encrypted is None:
            return None
        return self._fernet.decrypt(encrypted.encode()).decode()

    def delete(self, name: str) -> None:
        data = self._load_all()
        data.pop(name, None)
        self._save_all(data)

    def has(self, name: str) -> bool:
        return name in self._load_all()

    def _load_all(self) -> dict[str, str]:
        if not self._vault_path.exists():
            return {}
        import json
        return json.loads(self._vault_path.read_text(encoding="utf-8"))

    def _save_all(self, data: dict[str, str]) -> None:
        import json
        self._vault_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
