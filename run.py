"""一键启动听课助手。"""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# 包名到模块名的映射（解决大小写敏感等问题）
_PKG_MODULE_MAP = {
    "PyQt6": "PyQt6",
    "pyaudio": "pyaudio",
    "dashscope": "dashscope",
    "openai": "openai",
    "cryptography": "cryptography",
    "pynput": "pynput",
    "winotify": "winotify",
    "lameenc": "lameenc",
}


def ensure_deps() -> None:
    """检查并安装缺失依赖。"""
    missing = []
    for pkg, module in _PKG_MODULE_MAP.items():
        if importlib.util.find_spec(module) is None:
            missing.append(pkg)

    if missing:
        print(f"正在安装缺失依赖: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing, "-q"])


if __name__ == "__main__":
    ensure_deps()
    from src.main import main
    main()
