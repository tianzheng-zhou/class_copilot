"""一键启动听课助手。"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def ensure_deps() -> None:
    """检查并安装缺失依赖。"""
    required = ["PyQt6", "pyaudio", "dashscope", "openai", "cryptography", "pynput", "winotify"]
    missing = []
    for pkg in required:
        try:
            __import__(pkg.lower().replace("-", "_").split("[")[0])
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"正在安装缺失依赖: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing, "-q"])


if __name__ == "__main__":
    ensure_deps()
    from src.main import main
    main()
