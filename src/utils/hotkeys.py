"""全局快捷键管理。"""

from __future__ import annotations

import logging
from typing import Callable

from pynput import keyboard

from src.config.constants import DEFAULT_HOTKEYS

logger = logging.getLogger(__name__)


class HotkeyManager:
    """全局快捷键管理器。"""

    def __init__(self) -> None:
        self._listener: keyboard.GlobalHotKeys | None = None
        self._bindings: dict[str, str] = dict(DEFAULT_HOTKEYS)
        self._callbacks: dict[str, Callable[[], None]] = {}

    def set_binding(self, action: str, hotkey: str) -> None:
        self._bindings[action] = hotkey

    def register(self, action: str, callback: Callable[[], None]) -> None:
        self._callbacks[action] = callback

    def start(self) -> None:
        hotkey_map: dict[str, Callable[[], None]] = {}
        for action, hotkey_str in self._bindings.items():
            cb = self._callbacks.get(action)
            if cb:
                hotkey_map[hotkey_str] = cb

        if hotkey_map:
            self._listener = keyboard.GlobalHotKeys(hotkey_map)
            self._listener.daemon = True
            self._listener.start()
            logger.info("全局快捷键已启动")

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
            logger.info("全局快捷键已停止")

    def restart(self) -> None:
        self.stop()
        self.start()
