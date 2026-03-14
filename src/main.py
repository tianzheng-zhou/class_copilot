"""听课助手入口。"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("class_copilot.log", encoding="utf-8"),
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
