"""Windows 系统通知。"""

from __future__ import annotations

from winotify import Notification

from src.config.constants import APP_NAME


def notify_question_detected(question_text: str) -> None:
    """检测到问题时发送 Windows 系统通知（静音）。"""
    toast = Notification(
        app_id=APP_NAME,
        title="检测到课堂提问",
        msg=question_text[:200],
    )
    toast.set_audio(None, suppress=True)  # 静音通知
    toast.show()


def notify_status(title: str, message: str) -> None:
    """通用状态通知。"""
    toast = Notification(
        app_id=APP_NAME,
        title=title,
        msg=message[:200],
    )
    toast.set_audio(None, suppress=True)
    toast.show()
