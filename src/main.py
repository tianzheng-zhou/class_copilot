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
    from src.app import App
    app = App()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
