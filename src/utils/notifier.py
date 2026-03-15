"""Windows 系统通知。"""

from __future__ import annotations

import logging

from winotify import Notification

from src.config.constants import APP_NAME

logger = logging.getLogger(__name__)


def notify_question_detected(question_text: str) -> None:
    """检测到问题时发送 Windows 系统通知（静音）。"""
    try:
        toast = Notification(
            app_id=APP_NAME,
            title="检测到课堂提问",
            msg=question_text[:200],
        )
        toast.set_audio(None, suppress=True)
        toast.show()
    except Exception:
        logger.debug("发送通知失败", exc_info=True)


def notify_status(title: str, message: str) -> None:
    """通用状态通知。"""
    try:
        toast = Notification(
            app_id=APP_NAME,
            title=title,
            msg=message[:200],
        )
        toast.set_audio(None, suppress=True)
        toast.show()
    except Exception:
        logger.debug("发送通知失败", exc_info=True)
