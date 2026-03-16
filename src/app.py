"""应用启动与初始化。"""

from __future__ import annotations

import atexit
import logging
import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
import os

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
        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.ico")
        if os.path.exists(icon_path):
            self._qt_app.setWindowIcon(QIcon(icon_path))
        self._qt_app.setApplicationName("copilot")
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

        # 注册紧急清理函数，作为崩溃时的额外保障
        atexit.register(self._emergency_cleanup)

    def _setup_hotkeys(self) -> None:
        # 从设置加载自定义快捷键
        hotkeys = self.settings.hotkeys
        for action, key in hotkeys.items():
            self.hotkey_mgr.set_binding(action, key)

        self.hotkey_mgr.register("toggle_listen", self.window.hotkey_toggle_listen)
        self.hotkey_mgr.register("manual_question", self.window.hotkey_force_answer)
        self.hotkey_mgr.register("toggle_window", self.window.hotkey_toggle_window)
        self.hotkey_mgr.register("copy_transcript", self.window.hotkey_copy_transcript)
        self.hotkey_mgr.register("toggle_answer_mode", self.window.hotkey_toggle_answer_mode)
        self.hotkey_mgr.register("active_question", self.window.hotkey_active_question)
        self.hotkey_mgr.register("toggle_llm_filter", self.window.hotkey_toggle_filter)

        self.hotkey_mgr.start()

    def _check_first_run(self) -> None:
        """首次运行时弹出 API Key 配置。"""
        if not self.settings.has_api_key(Settings.DASHSCOPE_API_KEY):
            dialog = SettingsDialog(self.settings, self.window)
            dialog.setWindowTitle("首次配置 - 请输入阿里云百炼 API Key")
            dialog.exec()
            self.session_mgr.refresh_llm()

    def run(self) -> int:
        self.window.show()
        # 使用 QTimer.singleShot 确保在事件循环启动后弹出首次运行对话框
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._check_first_run)
        try:
            return self._qt_app.exec()
        finally:
            self.hotkey_mgr.stop()
            self.session_mgr.cleanup()

    def _emergency_cleanup(self) -> None:
        """崩溃时的紧急资源清理。"""
        try:
            if self.session_mgr.is_listening:
                self.session_mgr.stop_session()
        except Exception:
            pass
