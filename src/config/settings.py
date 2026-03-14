"""应用设置管理。"""

from __future__ import annotations

import json
from pathlib import Path

from src.config.constants import DEFAULT_HOTKEYS, DB_FILENAME
from src.utils.crypto import KeyVault

_DEFAULT_SETTINGS = {
    "microphone_index": -1,  # -1 = 系统默认
    "language": "zh",  # zh / en
    "asr_model": "fun-asr-realtime",  # ASR 模型
    "answer_mode_concise": True,
    "answer_mode_detailed": True,
    "translation_enabled": True,
    "bilingual_display": True,
    "storage_path": "",
    "hotkeys": dict(DEFAULT_HOTKEYS),
    "llm_filter_teacher_only": True,
}


class Settings:
    """统一管理应用设置与 API Key。"""

    def __init__(self, config_dir: str | Path | None = None) -> None:
        if config_dir is None:
            config_dir = Path.home() / ".class_copilot"
        self._config_dir = Path(config_dir)
        self._config_dir.mkdir(parents=True, exist_ok=True)

        self._settings_path = self._config_dir / "settings.json"
        self._vault = KeyVault(self._config_dir / "vault.json")
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self._settings_path.exists():
            self._data = json.loads(self._settings_path.read_text(encoding="utf-8"))
        else:
            self._data = dict(_DEFAULT_SETTINGS)
            self._save()

        # 填充缺失的默认值
        for k, v in _DEFAULT_SETTINGS.items():
            if k not in self._data:
                self._data[k] = v

    def _save(self) -> None:
        self._settings_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── 通用 getter / setter ──

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self._save()

    # ── API Keys（加密存储）──

    def set_api_key(self, name: str, value: str) -> None:
        self._vault.store(name, value)

    def get_api_key(self, name: str) -> str | None:
        return self._vault.retrieve(name)

    def has_api_key(self, name: str) -> bool:
        return self._vault.has(name)

    # ── 便捷属性 ──

    @property
    def db_path(self) -> Path:
        storage = self._data.get("storage_path")
        if storage:
            return Path(storage) / DB_FILENAME
        return self._config_dir / DB_FILENAME

    @property
    def audio_dir(self) -> Path:
        storage = self._data.get("storage_path")
        if storage:
            return Path(storage) / "recordings"
        return self._config_dir / "recordings"

    @property
    def config_dir(self) -> Path:
        return self._config_dir

    @property
    def language(self) -> str:
        return self._data.get("language", "zh")

    @property
    def microphone_index(self) -> int:
        return self._data.get("microphone_index", -1)

    @property
    def hotkeys(self) -> dict[str, str]:
        return self._data.get("hotkeys", dict(DEFAULT_HOTKEYS))

    @property
    def llm_filter_teacher_only(self) -> bool:
        return self._data.get("llm_filter_teacher_only", True)

    @property
    def answer_mode_concise(self) -> bool:
        return self._data.get("answer_mode_concise", True)

    @property
    def answer_mode_detailed(self) -> bool:
        return self._data.get("answer_mode_detailed", True)

    @property
    def asr_model(self) -> str:
        return self._data.get("asr_model", "fun-asr-realtime")

    # ── 阿里云百炼 API Key（ASR + LLM 共用）──
    DASHSCOPE_API_KEY = "dashscope_api_key"
