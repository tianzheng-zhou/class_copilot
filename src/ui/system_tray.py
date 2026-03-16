"""系统托盘图标。"""

from __future__ import annotations

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget


class SystemTray(QSystemTrayIcon):
    """系统托盘图标与菜单。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)

        # 使用默认应用图标
        icon = parent.windowIcon()
        if icon.isNull():
            style = parent.style()
            icon = style.standardIcon(style.StandardPixmap.SP_ComputerIcon) if style else QIcon()
        self.setIcon(icon)
        self.setToolTip("copilot")

        self._menu = QMenu()
        self._show_action = QAction("显示/隐藏", self)
        self._menu.addAction(self._show_action)
        self._menu.addSeparator()

        self._start_action = QAction("开始监听", self)
        self._menu.addAction(self._start_action)

        self._stop_action = QAction("停止监听", self)
        self._stop_action.setEnabled(False)
        self._menu.addAction(self._stop_action)

        self._menu.addSeparator()
        self._quit_action = QAction("退出", self)
        self._menu.addAction(self._quit_action)

        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_action.trigger()

    @property
    def show_action(self) -> QAction:
        return self._show_action

    @property
    def start_action(self) -> QAction:
        return self._start_action

    @property
    def stop_action(self) -> QAction:
        return self._stop_action

    @property
    def quit_action(self) -> QAction:
        return self._quit_action

    def set_listening(self, listening: bool) -> None:
        self._start_action.setEnabled(not listening)
        self._stop_action.setEnabled(listening)
        self.setToolTip("copilot" + (" - 正在监听" if listening else ""))
