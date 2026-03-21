"""一键启动听课助手"""

import subprocess
import sys

def main():
    # 确保依赖已安装
    try:
        import fastapi
        import uvicorn
    except ImportError:
        print("正在安装依赖...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

    # 启动应用
    from class_copilot.__main__ import main as app_main
    app_main()

if __name__ == "__main__":
    main()
