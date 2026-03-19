"""系统托盘服务 - pystray"""

import asyncio
import threading
import webbrowser

from loguru import logger

_tray_icon = None
_main_loop: asyncio.AbstractEventLoop | None = None


def _create_image():
    """创建托盘图标"""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 画一个简单的麦克风图标
    draw.ellipse([20, 8, 44, 32], fill=(100, 200, 255, 255))
    draw.rectangle([28, 32, 36, 48], fill=(100, 200, 255, 255))
    draw.rectangle([18, 48, 46, 52], fill=(100, 200, 255, 255))

    return img


def _on_open(icon, item):
    """打开浏览器"""
    from class_copilot.config import settings
    webbrowser.open(f"http://127.0.0.1:{settings.server_port}")


def _on_toggle_listen(icon, item):
    """切换监听状态"""
    if _main_loop:
        from class_copilot.services.session_manager import session_manager
        asyncio.run_coroutine_threadsafe(session_manager.toggle_listening(), _main_loop)


def _on_quit(icon, item):
    """退出应用"""
    logger.info("用户从托盘退出")
    icon.stop()
    import os
    os._exit(0)


def start_tray():
    """在独立线程中启动系统托盘"""
    global _tray_icon

    try:
        import pystray
        from pystray import MenuItem

        _tray_icon = pystray.Icon(
            name="class_copilot",
            icon=_create_image(),
            title="听课助手",
            menu=pystray.Menu(
                MenuItem("打开浏览器", _on_open, default=True),
                MenuItem("开始/停止监听", _on_toggle_listen),
                pystray.Menu.SEPARATOR,
                MenuItem("退出", _on_quit),
            ),
        )

        logger.info("系统托盘已启动")
        _tray_icon.run()

    except Exception as e:
        logger.warning("系统托盘启动失败: {}", e)


def set_main_loop(loop: asyncio.AbstractEventLoop):
    """设置主事件循环引用"""
    global _main_loop
    _main_loop = loop


def update_icon_recording(is_recording: bool):
    """更新托盘图标状态"""
    global _tray_icon
    if _tray_icon is None:
        return

    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    color = (255, 80, 80, 255) if is_recording else (100, 200, 255, 255)

    draw.ellipse([20, 8, 44, 32], fill=color)
    draw.rectangle([28, 32, 36, 48], fill=color)
    draw.rectangle([18, 48, 46, 52], fill=color)

    try:
        _tray_icon.icon = img
        _tray_icon.title = "听课助手 - " + ("正在监听" if is_recording else "就绪")
    except Exception:
        pass
