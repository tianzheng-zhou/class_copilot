"""全局快捷键服务 - keyboard 库"""

import asyncio
import threading

import keyboard
from loguru import logger


class HotkeyService:
    """全局快捷键管理"""

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._registered = False
        self._callbacks: dict[str, callable] = {}

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def register_hotkeys(self, callbacks: dict[str, callable]):
        """
        注册全局快捷键。
        callbacks: {"ctrl+shift+s": async_func, ...}
        """
        if self._registered:
            self.unregister_all()

        self._callbacks = callbacks

        default_hotkeys = {
            "ctrl+shift+s": "toggle_listening",
            "ctrl+shift+q": "manual_detect",
            "ctrl+shift+h": "toggle_window",
            "ctrl+shift+c": "copy_answer",
            "ctrl+shift+t": "toggle_answer_type",
            "ctrl+shift+a": "show_chat",
            "ctrl+shift+f": "toggle_filter_mode",
            "ctrl+shift+r": "manual_refine",
        }

        for hotkey, action_name in default_hotkeys.items():
            if action_name in callbacks:
                callback = callbacks[action_name]
                keyboard.add_hotkey(hotkey, lambda cb=callback: self._dispatch(cb))
                logger.debug("注册快捷键: {} -> {}", hotkey, action_name)

        self._registered = True
        logger.info("全局快捷键已注册")

    def _dispatch(self, callback):
        """将回调分发到异步事件循环"""
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(callback(), self._loop)

    def unregister_all(self):
        """注销所有快捷键"""
        try:
            keyboard.unhook_all_hotkeys()
            self._registered = False
            logger.info("全局快捷键已注销")
        except Exception as e:
            logger.warning("注销快捷键异常: {}", e)
