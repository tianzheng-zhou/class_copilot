"""应用启动与初始化。"""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication

from src.config.settings import Settings
from src.core.session_manager import SessionManager
from src.ui.main_window import MainWindow
from src.ui.settings_dialog import SettingsDialog
from src.ui.styles import DARK_THEME
from src.utils.hotkeys import HotkeyManager

logger = logging.getLogger(__name__)


class App:
    """应用主类。"""

    def __init__(self) -> None:
        self._qt_app = QApplication(sys.argv)
        self._qt_app.setApplicationName("听课助手")
        self._qt_app.setOrganizationName("class_copilot")
        self._qt_app.setStyleSheet(DARK_THEME)

        # 初始化设置
        self.settings = Settings()

        # 初始化会话管理器
        self.session_mgr = SessionManager(self.settings)

        # 主窗口
        self.window = MainWindow(self.session_mgr)

        # 全局快捷键
        self.hotkey_mgr = HotkeyManager()
        self._setup_hotkeys()

    def _setup_hotkeys(self) -> None:
        # 从设置加载自定义快捷键
        hotkeys = self.settings.hotkeys
        for action, key in hotkeys.items():
            self.hotkey_mgr.set_binding(action, key)

        self.hotkey_mgr.register("toggle_listen", self.window.hotkey_toggle_listen)
        self.hotkey_mgr.register("manual_question", self.window.hotkey_manual_question)
        self.hotkey_mgr.register("toggle_window", self.window.hotkey_toggle_window)
        self.hotkey_mgr.register("copy_answer", self.window.hotkey_copy_answer)
        self.hotkey_mgr.register("toggle_answer_mode", self.window.hotkey_toggle_answer_mode)
        self.hotkey_mgr.register("active_question", self.window.hotkey_active_question)
        self.hotkey_mgr.register("toggle_llm_filter", self.window.hotkey_toggle_filter)

        self.hotkey_mgr.start()

    def _check_first_run(self) -> None:
        """首次运行时弹出 API Key 配置。"""
        needs_setup = (
            not self.settings.has_api_key(Settings.IFLYTEK_APP_ID)
            or not self.settings.has_api_key(Settings.DASHSCOPE_API_KEY)
        )
        if needs_setup:
            dialog = SettingsDialog(self.settings, self.window)
            dialog.setWindowTitle("首次配置 - 请输入 API Key")
            dialog.exec()
            self.session_mgr.refresh_llm()

    def run(self) -> int:
        self.window.show()
        self._check_first_run()
        try:
            return self._qt_app.exec()
        finally:
            self.hotkey_mgr.stop()
            self.session_mgr.cleanup()
