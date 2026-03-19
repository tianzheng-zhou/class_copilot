"""Windows 通知服务 - 无声 toast 通知"""

import asyncio
from loguru import logger


class NotificationService:
    """Windows 系统通知（无声）"""

    def __init__(self):
        self._toaster = None

    def _get_toaster(self):
        if self._toaster is None:
            try:
                from win10toast_click import ToastNotifier
                self._toaster = ToastNotifier()
            except ImportError:
                logger.warning("win10toast_click 未安装，通知功能不可用")
        return self._toaster

    async def notify_question(self, question: str):
        """检测到问题时发送通知"""
        toaster = self._get_toaster()
        if toaster is None:
            return

        try:
            await asyncio.to_thread(
                toaster.show_toast,
                "📝 检测到课堂问题",
                question[:200],
                duration=5,
                threaded=False,
            )
        except Exception as e:
            logger.debug("发送通知失败（静默降级）: {}", e)

    async def notify_info(self, title: str, message: str):
        """发送信息通知"""
        toaster = self._get_toaster()
        if toaster is None:
            return

        try:
            await asyncio.to_thread(
                toaster.show_toast,
                title,
                message[:200],
                duration=3,
                threaded=False,
            )
        except Exception:
            pass
