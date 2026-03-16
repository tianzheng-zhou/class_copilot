"""听课助手入口。"""

import logging
import sys
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            "class_copilot.log", maxBytes=5 * 1024 * 1024, backupCount=3,
            encoding="utf-8",
        ),
    ],
)


def main() -> None:
    import os
    # 优化 Windows 渲染性能，减少窗口闪烁
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QSG_RENDER_LOOP", "basic")

    from src.app import App
    app = App()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
